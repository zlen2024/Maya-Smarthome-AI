import 'package:flutter/material.dart';
import '../services/voice_service.dart';

/// Full-screen voice UI opened by the mic button or the Quick Settings tile.
/// On open Maya greets the user (TTS) then listens; a language toggle up top
/// switches ASR + TTS locale and re-greets. Breathing orb with ripple rings,
/// live transcript, and Maya's spoken reply.
class VoiceOverlayScreen extends StatefulWidget {
  const VoiceOverlayScreen({super.key});

  /// Guard so the QS tile / FAB can't stack multiple overlays.
  static bool isOpen = false;

  @override
  State<VoiceOverlayScreen> createState() => _VoiceOverlayScreenState();
}

class _VoiceOverlayScreenState extends State<VoiceOverlayScreen>
    with TickerProviderStateMixin {
  late final AnimationController _breath =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 2200))
        ..repeat(reverse: true);
  late final AnimationController _ripple =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 2600))
        ..repeat();
  String _heard = '';
  String _reply = '';
  String _error = '';
  Future<void>? _flow;

  @override
  void initState() {
    super.initState();
    VoiceOverlayScreen.isOpen = true;
    WidgetsBinding.instance.addPostFrameCallback((_) => _start(greet: true));
  }

  @override
  void dispose() {
    _breath.dispose();
    _ripple.dispose();
    VoiceOverlayScreen.isOpen = false;
    // Don't leave the mic/tts running if the user closes mid-flow.
    VoiceService.cancel();
    super.dispose();
  }

  /// Greet (optional) then listen; [greet] on open and on language change.
  void _start({required bool greet}) {
    setState(() {
      _heard = '';
      _reply = '';
      _error = '';
    });
    _flow = _run(greet);
  }

  Future<void> _run(bool greet) async {
    try {
      await VoiceService.runOnce(
        greet: greet,
        onTranscript: (t) => mounted ? setState(() => _heard = t) : null,
        onReply: (r) => mounted ? setState(() => _reply = r) : null,
      );
    } catch (e) {
      if (mounted) {
        setState(() => _error = e.toString().replaceFirst('Exception: ', ''));
      }
    }
  }

  Future<void> _changeLang(VoiceLang l) async {
    if (l == VoiceService.lang.value) return;
    await VoiceService.setLang(l);
    if (mounted) setState(() {});
    await VoiceService.cancel(); // interrupt current greeting/listen/reply
    await _flow; // let the interrupted flow settle back to idle
    _start(greet: true); // re-greet + listen in the new language
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      backgroundColor: const Color(0xFF05060A),
      body: Container(
        decoration: BoxDecoration(
          gradient: RadialGradient(
            radius: 1.1,
            center: const Alignment(0, -0.15),
            colors: [cs.primary.withOpacity(0.16), const Color(0xFF05060A)],
          ),
        ),
        child: SafeArea(
          child: Stack(
            children: [
              Align(alignment: Alignment.topCenter, child: _langToggle(cs)),
              Align(
                alignment: Alignment.topRight,
                child: IconButton(
                  iconSize: 28,
                  icon: const Icon(Icons.close_rounded, color: Colors.white54),
                  onPressed: () => Navigator.of(context).maybePop(),
                ),
              ),
              Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    _orb(cs),
                    const SizedBox(height: 44),
                    ValueListenableBuilder<VoiceState>(
                      valueListenable: VoiceService.state,
                      builder: (context, state, _) => Text(
                        _statusLine(state),
                        style: TextStyle(
                          color: Colors.white.withOpacity(0.55),
                          fontSize: 14,
                          letterSpacing: 0.3,
                        ),
                      ),
                    ),
                    const SizedBox(height: 18),
                    _transcript(cs),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _langToggle(ColorScheme cs) {
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: ValueListenableBuilder<VoiceLang>(
        valueListenable: VoiceService.lang,
        builder: (context, current, _) {
          return Container(
            padding: const EdgeInsets.all(4),
            decoration: BoxDecoration(
              color: Colors.white.withOpacity(0.06),
              borderRadius: BorderRadius.circular(30),
              border: Border.all(color: Colors.white.withOpacity(0.08)),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: VoiceLang.values.map((l) {
                final active = l == current;
                return GestureDetector(
                  onTap: () => _changeLang(l),
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 180),
                    padding:
                        const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
                    decoration: BoxDecoration(
                      color: active ? cs.primary : Colors.transparent,
                      borderRadius: BorderRadius.circular(24),
                    ),
                    child: Text(
                      l.label,
                      style: TextStyle(
                        color: active ? Colors.white : Colors.white60,
                        fontWeight:
                            active ? FontWeight.w700 : FontWeight.w500,
                        fontSize: 13.5,
                      ),
                    ),
                  ),
                );
              }).toList(),
            ),
          );
        },
      ),
    );
  }

  Widget _orb(ColorScheme cs) {
    return ValueListenableBuilder<VoiceState>(
      valueListenable: VoiceService.state,
      builder: (context, state, _) {
        final active =
            state == VoiceState.listening || state == VoiceState.speaking;
        return GestureDetector(
          onTap: state == VoiceState.idle ? () => _start(greet: false) : null,
          child: SizedBox(
            width: 240,
            height: 240,
            child: AnimatedBuilder(
              animation: Listenable.merge([_breath, _ripple]),
              builder: (context, _) {
                final breath = 0.96 + _breath.value * 0.08;
                return CustomPaint(
                  painter:
                      active ? _RipplePainter(_ripple.value, cs.primary) : null,
                  child: Center(
                    child: Transform.scale(
                      scale: breath,
                      child: Container(
                        width: 140,
                        height: 140,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          gradient: LinearGradient(
                            colors: [cs.primary, cs.tertiary],
                            begin: Alignment.topLeft,
                            end: Alignment.bottomRight,
                          ),
                          boxShadow: [
                            BoxShadow(
                              color: cs.primary.withOpacity(0.5),
                              blurRadius: 48,
                              spreadRadius: 4,
                            ),
                          ],
                        ),
                        child: Icon(
                          state == VoiceState.thinking
                              ? Icons.auto_awesome_rounded
                              : state == VoiceState.speaking
                                  ? Icons.graphic_eq_rounded
                                  : Icons.mic_rounded,
                          size: 52,
                          color: Colors.white,
                        ),
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
        );
      },
    );
  }

  Widget _transcript(ColorScheme cs) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 36),
      child: Column(
        children: [
          ValueListenableBuilder<String>(
            valueListenable: VoiceService.partialText,
            builder: (context, partial, _) {
              final shown = _heard.isNotEmpty ? _heard : partial;
              if (shown.isEmpty) return const SizedBox(height: 4);
              return Text(
                '"$shown"',
                textAlign: TextAlign.center,
                style: const TextStyle(
                    color: Colors.white,
                    fontSize: 19,
                    height: 1.35,
                    fontWeight: FontWeight.w600),
              );
            },
          ),
          if (_reply.isNotEmpty) ...[
            const SizedBox(height: 24),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
              decoration: BoxDecoration(
                color: cs.primary.withOpacity(0.12),
                borderRadius: BorderRadius.circular(18),
                border: Border.all(color: cs.primary.withOpacity(0.35)),
              ),
              child: Text(
                _reply,
                textAlign: TextAlign.center,
                style: TextStyle(
                    color: Colors.white.withOpacity(0.95),
                    fontSize: 18,
                    height: 1.4),
              ),
            ),
          ],
          if (_error.isNotEmpty)
            Text(_error,
                textAlign: TextAlign.center,
                style: TextStyle(color: cs.error, fontSize: 15)),
        ],
      ),
    );
  }

  String _statusLine(VoiceState state) {
    switch (state) {
      case VoiceState.listening:
        return 'Listening…';
      case VoiceState.thinking:
        return 'Maya is thinking…';
      case VoiceState.speaking:
        return 'Maya is speaking…';
      case VoiceState.idle:
        return _reply.isNotEmpty || _error.isNotEmpty
            ? 'Tap the orb to speak again'
            : 'Tap the orb to speak';
    }
  }
}

/// Concentric rings expanding out from the orb while active.
class _RipplePainter extends CustomPainter {
  _RipplePainter(this.t, this.color);
  final double t; // 0..1 repeating
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final center = size.center(Offset.zero);
    const base = 72.0;
    final maxR = size.width / 2;
    for (var i = 0; i < 3; i++) {
      final phase = (t + i / 3) % 1.0;
      final r = base + (maxR - base) * phase;
      final paint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2
        ..color = color.withOpacity((1 - phase) * 0.35);
      canvas.drawCircle(center, r, paint);
    }
  }

  @override
  bool shouldRepaint(_RipplePainter old) => old.t != t;
}
