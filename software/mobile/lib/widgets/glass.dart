import 'package:flutter/material.dart';
import '../theme/accents.dart';

// The house surfaces. The file and class names are kept from the glass theme
// so screens did not have to change; what they draw is now flat: a plaster
// room, paper cards with a hairline edge, and ink for anything that is on.

/// The room behind every screen: the palette's base, nothing else.
class AuroraBackground extends StatelessWidget {
  final Palette palette;
  final Widget child;
  const AuroraBackground({super.key, required this.palette, required this.child});

  @override
  Widget build(BuildContext context) => ColoredBox(color: palette.base, child: child);
}

/// The app's card. A paper surface with a hairline border. When [glow] is set
/// (a device that is on) the border turns to ink and thickens — contrast, not
/// colour, says "on". The colour passed in is ignored apart from being set.
class GlassSurface extends StatelessWidget {
  final Widget child;
  final EdgeInsets padding;
  final double radius;
  final VoidCallback? onTap;
  final Color? glow;

  const GlassSurface({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(18),
    this.radius = 20,
    this.onTap,
    this.glow,
  });

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    final active = glow != null;
    final shape = RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(radius),
      side: BorderSide(color: active ? p.ink : p.line, width: active ? 1.8 : 1),
    );
    return Material(
      color: p.surface,
      shape: shape,
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        splashColor: p.ink.withOpacity(0.06),
        highlightColor: p.ink.withOpacity(0.04),
        child: Padding(padding: padding, child: child),
      ),
    );
  }
}

/// Small status chip ("3 of 3 online"): an outlined pill with an optional dot.
class GlassPill extends StatelessWidget {
  final Widget child;
  final Color? dot;
  const GlassPill({super.key, required this.child, this.dot});

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
      decoration: BoxDecoration(
        color: p.surface,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: p.line),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (dot != null) ...[
            Container(
              width: 7,
              height: 7,
              decoration: BoxDecoration(shape: BoxShape.circle, color: dot),
            ),
            const SizedBox(width: 7),
          ],
          DefaultTextStyle.merge(
            style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: p.ink),
            child: child,
          ),
        ],
      ),
    );
  }
}
