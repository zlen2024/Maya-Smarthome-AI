import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

/// Cloud STT via Groq's whisper-large-v3 (BYOK). Records a short WAV and uploads
/// it with the user's OWN API key (entered in Settings, stored on-device).
/// Accurate for Malay/Manglish; needs internet. Audio leaves the device to
/// Groq — the user opts in by enabling it + providing a key.
class GroqStt {
  static final AudioRecorder _recorder = AudioRecorder();
  static Completer<void>? _endWait;
  static bool _cancelled = false;

  static Future<bool> hasPermission() => _recorder.hasPermission();

  /// Record up to [maxSeconds] (or until [stop]), upload to Groq, return text.
  /// [onCaptured] fires when recording ends and the upload/transcribe begins.
  static Future<String> transcribe(String apiKey, String lang,
      {int maxSeconds = 6, void Function()? onCaptured}) async {
    _cancelled = false;
    final tmp = await getTemporaryDirectory();
    final wav = '${tmp.path}/maya_groq.wav';
    await _recorder.start(
      const RecordConfig(
          encoder: AudioEncoder.wav, sampleRate: 16000, numChannels: 1),
      path: wav,
    );
    _endWait = Completer<void>();
    await Future.any([
      Future.delayed(Duration(seconds: maxSeconds)),
      _endWait!.future,
    ]);
    _endWait = null;
    if (await _recorder.isRecording()) await _recorder.stop();
    if (_cancelled) {
      _del(wav);
      return '';
    }

    onCaptured?.call();
    final req = http.MultipartRequest('POST',
        Uri.parse('https://api.groq.com/openai/v1/audio/transcriptions'));
    req.headers['Authorization'] = 'Bearer $apiKey';
    req.fields['model'] = 'whisper-large-v3';
    req.fields['temperature'] = '0';
    req.fields['response_format'] = 'json';
    req.fields['language'] = lang; // 'en' | 'ms'
    req.files.add(await http.MultipartFile.fromPath('file', wav));

    final resp = await http.Response.fromStream(await req.send());
    _del(wav);
    if (resp.statusCode != 200) {
      throw Exception('Groq ${resp.statusCode}: ${_briefErr(resp.body)}');
    }
    final data = jsonDecode(resp.body) as Map<String, dynamic>;
    return (data['text'] ?? '').toString().trim();
  }

  static void _del(String p) {
    try {
      File(p).deleteSync();
    } catch (_) {}
  }

  static String _briefErr(String body) {
    try {
      return (jsonDecode(body)['error']?['message'] ?? body).toString();
    } catch (_) {
      return body;
    }
  }

  static void _endNow() {
    if (_endWait != null && !_endWait!.isCompleted) _endWait!.complete();
  }

  static Future<void> stop() async => _endNow();

  static Future<void> cancel() async {
    _cancelled = true;
    _endNow();
    if (await _recorder.isRecording()) await _recorder.stop();
  }
}
