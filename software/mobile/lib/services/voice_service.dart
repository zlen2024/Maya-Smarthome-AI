import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:speech_to_text/speech_to_text.dart';
import 'api_service.dart';
import 'groq_stt.dart';

/// A language the user can pick on the voice screen: `sttLocale` for the device
/// recognizer, `code` ('en'/'ms') for Groq, `ttsLocale` for the TTS voice.
enum VoiceLang {
  english('en', 'English', 'en_US', 'en-US'),
  malay('ms', 'Malay', 'ms_MY', 'ms-MY');

  const VoiceLang(this.code, this.label, this.sttLocale, this.ttsLocale);
  final String code;
  final String label;
  final String sttLocale;
  final String ttsLocale;
}

/// Voice pipeline: transcribe speech (device recognizer by default; optionally
/// Groq whisper-large-v3 with the user's own key), send to Maya's private
/// endpoint, then speak her reply (flutter_tts). Not written to house chat.
class VoiceService {
  static final SpeechToText _stt = SpeechToText();
  static bool _sttInit = false;
  static Completer<String>? _deviceCompleter;

  static final FlutterTts _tts = FlutterTts();
  static bool _ttsInit = false;

  static final ValueNotifier<VoiceLang> lang = ValueNotifier(VoiceLang.english);

  // ── Groq (BYOK) settings, persisted ────────────────────────────
  static bool groqEnabled = false;
  static String groqKey = '';
  static bool get _useGroq => groqEnabled && groqKey.trim().isNotEmpty;

  static Future<void> loadSettings() async {
    final prefs = await SharedPreferences.getInstance();
    final code = prefs.getString('voice_lang');
    lang.value = VoiceLang.values
        .firstWhere((l) => l.code == code, orElse: () => VoiceLang.english);
    groqEnabled = prefs.getBool('groq_enabled') ?? false;
    groqKey = prefs.getString('groq_key') ?? '';
    _ttsInit = false;
  }

  static Future<void> setLang(VoiceLang l) async {
    lang.value = l;
    _ttsInit = false; // re-init TTS voice on next speak
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('voice_lang', l.code);
  }

  static Future<void> setGroq({bool? enabled, String? key}) async {
    final prefs = await SharedPreferences.getInstance();
    if (enabled != null) {
      groqEnabled = enabled;
      await prefs.setBool('groq_enabled', enabled);
    }
    if (key != null) {
      groqKey = key.trim();
      await prefs.setString('groq_key', groqKey);
    }
  }

  /// idle / listening / thinking / speaking.
  static final ValueNotifier<VoiceState> state = ValueNotifier(VoiceState.idle);

  /// Live interim words (device engine only; Groq has no partials).
  static final ValueNotifier<String> partialText = ValueNotifier('');

  static const int maxSeconds = 8;
  static bool _cancelled = false;

  /// Name-personalized greeting in the selected language.
  static String greeting() {
    final name = ApiService.userName.trim();
    final who = name.isEmpty ? '' : ' $name';
    switch (lang.value) {
      case VoiceLang.english:
        return 'Hi$who, how can I help?';
      case VoiceLang.malay:
        return 'Hai$who, apa yang boleh saya bantu?';
    }
  }

  /// Full flow. Returns Maya's reply text, or throws with a user-facing message.
  static Future<String> runOnce({
    void Function(String)? onTranscript,
    void Function(String)? onReply,
    bool greet = false,
  }) async {
    if (state.value != VoiceState.idle) {
      throw Exception('Maya is already listening.');
    }
    _cancelled = false;
    partialText.value = '';
    try {
      if (greet) {
        state.value = VoiceState.speaking;
        await _speak(greeting());
        if (_cancelled) return '';
      }
      state.value = VoiceState.listening;
      final transcript = _useGroq ? await _groqCapture() : await _deviceCapture();

      if (_cancelled) return '';
      if (transcript.trim().isEmpty) {
        throw Exception("I didn't catch that.");
      }
      onTranscript?.call(transcript);
      state.value = VoiceState.thinking;
      final reply = await ApiService.sendVoiceCommand(transcript);
      onReply?.call(reply);
      state.value = VoiceState.speaking;
      await _speak(reply);
      return reply;
    } finally {
      state.value = VoiceState.idle;
    }
  }

  // ── Device recognizer (default) — streams live partials ────────
  static Future<String> _deviceCapture() async {
    if (!_sttInit) {
      _sttInit = await _stt.initialize(
          onError: (e) => debugPrint('stt error: ${e.errorMsg}'));
    }
    if (!_sttInit) {
      throw Exception('Speech recognition unavailable (check mic permission).');
    }
    final completer = Completer<String>();
    _deviceCompleter = completer;
    String words = '';
    await _stt.listen(
      onResult: (r) {
        words = r.recognizedWords;
        partialText.value = words;
        if (r.finalResult && !completer.isCompleted) completer.complete(words);
      },
      localeId: lang.value.sttLocale,
      listenFor: const Duration(seconds: maxSeconds),
      pauseFor: const Duration(seconds: 3),
      listenOptions:
          SpeechListenOptions(cancelOnError: true, partialResults: true),
    );
    final t = await completer.future
        .timeout(const Duration(seconds: maxSeconds + 2), onTimeout: () => words);
    await _stt.stop();
    return t;
  }

  // ── Groq whisper-large-v3 (opt-in, BYOK) ───────────────────────
  static Future<String> _groqCapture() async {
    if (!await GroqStt.hasPermission()) {
      throw Exception('Microphone permission denied.');
    }
    return GroqStt.transcribe(
      groqKey,
      lang.value.code,
      maxSeconds: 6,
      onCaptured: () => state.value = VoiceState.thinking, // uploading/decoding
    );
  }

  /// Finish capture early.
  static Future<void> stop() async =>
      _useGroq ? GroqStt.stop() : _stt.stop();

  /// Abort without sending (used on language/engine switch mid-flow).
  static Future<void> cancel() async {
    _cancelled = true;
    await GroqStt.cancel();
    try {
      await _stt.cancel();
    } catch (_) {}
    if (_deviceCompleter != null && !_deviceCompleter!.isCompleted) {
      _deviceCompleter!.complete('');
    }
    await _tts.stop();
  }

  /// Speak text on-device. Best-effort — a TTS failure must not break the flow.
  static Future<void> _speak(String text) async {
    if (text.trim().isEmpty) return;
    try {
      if (!_ttsInit) {
        await _tts.setLanguage(lang.value.ttsLocale);
        await _tts.setSpeechRate(0.5);
        await _tts.setPitch(1.0);
        await _tts.awaitSpeakCompletion(true);
        _ttsInit = true;
      }
      await _tts.stop();
      await _tts.speak(text);
    } catch (e) {
      debugPrint('tts failed: $e');
    }
  }
}

enum VoiceState { idle, listening, thinking, speaking }
