import 'dart:math' as math;
import 'dart:ui';
import 'package:flutter/material.dart';
import '../theme/accents.dart';

/// The aurora canvas: a solid base tint with soft radial orbs and a field of
/// floating, drifting, and pulsing blurry dust particles.
class AuroraBackground extends StatefulWidget {
  final AccentPreset accent;
  final Widget child;
  const AuroraBackground({super.key, required this.accent, required this.child});

  @override
  State<AuroraBackground> createState() => _AuroraBackgroundState();
}

class _AuroraBackgroundState extends State<AuroraBackground>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;
  late final List<_ParticlePreset> _particles;

  @override
  void initState() {
    super.initState();
    // One loop cycle for continuous movement
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 15),
    )..repeat(reverse: true);

    _generateParticles();
  }

  void _generateParticles() {
    final rand = math.Random(42); // Seeded random for consistent placements
    _particles = List.generate(35, (index) {
      return _ParticlePreset(
        initialX: rand.nextDouble(),
        initialY: rand.nextDouble(),
        speedX: (rand.nextDouble() * 2 - 1) * 0.04, // slow horizontal drift
        speedY: -rand.nextDouble() * 0.08 - 0.03,   // gentle upward float
        size: rand.nextDouble() * 50 + 15,          // blurry particle size (15 to 65px)
        maxOpacity: rand.nextDouble() * 0.28 + 0.12, // soft glow opacity
        colorIndex: rand.nextInt(3),                // index from accent.orbs
        swingAmp: rand.nextDouble() * 0.04 + 0.015,  // sway offset
        swingFreq: rand.nextDouble() * 3 + 1.2,     // sway speed multiplier
        phase: rand.nextDouble() * math.pi * 2,
      );
    });
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final accent = widget.accent;
    return Container(
      color: accent.base,
      child: AnimatedBuilder(
        animation: _ctrl,
        builder: (context, child) {
          return Stack(
            children: [
              Positioned.fill(
                child: CustomPaint(
                  painter: _AuroraPainter(
                    particles: _particles,
                    colors: accent.orbs,
                    time: _ctrl.value,
                  ),
                ),
              ),
              widget.child,
            ],
          );
        },
      ),
    );
  }
}

class _ParticlePreset {
  final double initialX;
  final double initialY;
  final double speedX;
  final double speedY;
  final double size;
  final double maxOpacity;
  final int colorIndex;
  final double swingAmp;
  final double swingFreq;
  final double phase;

  const _ParticlePreset({
    required this.initialX,
    required this.initialY,
    required this.speedX,
    required this.speedY,
    required this.size,
    required this.maxOpacity,
    required this.colorIndex,
    required this.swingAmp,
    required this.swingFreq,
    required this.phase,
  });
}

class _AuroraPainter extends CustomPainter {
  final List<_ParticlePreset> particles;
  final List<Color> colors;
  final double time; // 0.0 -> 1.0 representing progress

  _AuroraPainter({
    required this.particles,
    required this.colors,
    required this.time,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint();

    // ── 1. Draw Large Ambient Glows (balanced purple left / blue right) ──
    // Violet top-left ambient
    _drawAmbientGlow(
      canvas,
      size,
      center: Offset(size.width * 0.15, size.height * 0.12),
      color: colors[0],
      radius: size.width * 0.8,
      opacity: 0.45,
      pulseSpeed: 0.8,
    );

    // Blue top-right ambient
    _drawAmbientGlow(
      canvas,
      size,
      center: Offset(size.width * 0.85, size.height * 0.35),
      color: colors[1],
      radius: size.width * 0.7,
      opacity: 0.42,
      pulseSpeed: 1.1,
    );

    // Teal bottom-center ambient
    if (colors.length > 2) {
      _drawAmbientGlow(
        canvas,
        size,
        center: Offset(size.width * 0.4, size.height * 0.75),
        color: colors[2],
        radius: size.width * 0.6,
        opacity: 0.22,
        pulseSpeed: 0.6,
      );
    }

    // ── 2. Draw Blurry Moving Dust Particles ──
    for (final p in particles) {
      // Linear drift over time with wrapping (0.0 to 1.0)
      double x = (p.initialX + p.speedX * time) % 1.0;
      double y = (p.initialY + p.speedY * time) % 1.0;

      // Add sway (sinusoidal wobble)
      final angle = time * 2 * math.pi * p.swingFreq + p.phase;
      x = (x + math.sin(angle) * p.swingAmp) % 1.0;
      y = (y + math.cos(angle * 0.85) * p.swingAmp) % 1.0;

      // Map to real pixels
      final px = x * size.width;
      final py = y * size.height;

      // Pulse opacity & size
      final pulse = math.sin(angle * 1.4);
      final currentOpacity = (p.maxOpacity * (0.8 + 0.2 * pulse)).clamp(0.0, 1.0);
      final currentSize = p.size * (0.85 + 0.15 * pulse);

      final color = colors[p.colorIndex % colors.length];

      // Blurry radial glow shader
      paint.shader = RadialGradient(
        colors: [color.withOpacity(currentOpacity), color.withOpacity(0.0)],
      ).createShader(Rect.fromCircle(center: Offset(px, py), radius: currentSize));

      canvas.drawCircle(Offset(px, py), currentSize, paint);
    }
  }

  void _drawAmbientGlow(
    Canvas canvas,
    Size size, {
    required Offset center,
    required Color color,
    required double radius,
    required double opacity,
    required double pulseSpeed,
  }) {
    final angle = time * 2 * math.pi * pulseSpeed;
    final pulse = math.sin(angle) * 0.05;
    final currentOpacity = (opacity + pulse).clamp(0.0, 1.0);
    final currentRadius = radius * (1.0 + math.cos(angle * 0.7) * 0.04);

    // Subtle drift of ambient centers
    final dx = math.sin(angle * 0.4) * (size.width * 0.03);
    final dy = math.cos(angle * 0.55) * (size.height * 0.02);
    final finalCenter = Offset(center.dx + dx, center.dy + dy);

    final paint = Paint()
      ..shader = RadialGradient(
        colors: [color.withOpacity(currentOpacity), color.withOpacity(0.0)],
      ).createShader(Rect.fromCircle(center: finalCenter, radius: currentRadius));

    canvas.drawCircle(finalCenter, currentRadius, paint);
  }

  @override
  bool shouldRepaint(covariant _AuroraPainter oldDelegate) {
    return oldDelegate.time != time || oldDelegate.colors != colors;
  }
}

/// App-wide frosted glass surface using native [BackdropFilter]. Every glass
/// card in the app shares the same tuning (blur, tint, radius) via this widget.
/// Adds tap support and an optional accent glow when active.
class GlassSurface extends StatelessWidget {
  final Widget child;
  final EdgeInsets padding;
  final double radius;
  final VoidCallback? onTap;

  /// When set, rims the surface in this accent and casts a matching glow —
  /// used to signal an "on" device.
  final Color? glow;

  const GlassSurface({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(18),
    this.radius = 24,
    this.onTap,
    this.glow,
  });

  @override
  Widget build(BuildContext context) {
    final card = ClipRRect(
      borderRadius: BorderRadius.circular(radius),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 18, sigmaY: 18),
        child: Container(
          decoration: BoxDecoration(
            color: (glow ?? Colors.white).withOpacity(0.14),
            borderRadius: BorderRadius.circular(radius),
            border: Border.all(
              color: glow != null
                  ? glow!.withOpacity(0.65)
                  : Colors.white.withOpacity(0.18),
              width: glow != null ? 1.6 : 1,
            ),
            boxShadow: glow != null
                ? [
                    BoxShadow(
                      color: glow!.withOpacity(0.30),
                      blurRadius: 32,
                      spreadRadius: -2,
                    ),
                  ]
                : null,
          ),
          padding: padding,
          child: child,
        ),
      ),
    );

    if (onTap == null) return card;
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: card,
    );
  }
}

/// Small frosted pill for status chips ("3 of 3 online"). Kept lightweight —
/// no backdrop blur needed on tiny chips.
class GlassPill extends StatelessWidget {
  final Widget child;
  final Color? dot;
  const GlassPill({super.key, required this.child, this.dot});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.07),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: Colors.white.withOpacity(0.10)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (dot != null) ...[
            Container(
              width: 7,
              height: 7,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: dot,
                boxShadow: [BoxShadow(color: dot!.withOpacity(0.6), blurRadius: 6)],
              ),
            ),
            const SizedBox(width: 7),
          ],
          DefaultTextStyle.merge(
            style: TextStyle(
              fontSize: 12.5,
              fontWeight: FontWeight.w600,
              color: Colors.white.withOpacity(0.85),
            ),
            child: child,
          ),
        ],
      ),
    );
  }
}
