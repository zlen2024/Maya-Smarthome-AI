import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// One house palette. The brand is a quiet, minimalist home: plaster walls,
/// charcoal ink, and contrast doing the work colour used to do. "On" is shown
/// by ink, not by a hue. Two palettes ship — a day one and a night one — and
/// the layout is identical across them.
///
/// It is a [ThemeExtension], so widgets read it with `context.pal` and rebuild
/// when the user switches palette.
class Palette extends ThemeExtension<Palette> {
  final String id;
  final String label;
  final Brightness brightness;

  /// The room: page background.
  final Color base;

  /// Cards and sheets, a step off the base.
  final Color surface;

  /// Pressed / recessed areas (tracks, inputs, icon wells).
  final Color sunken;

  /// Primary text, icons, and every "on" state.
  final Color ink;

  /// Secondary text and idle icons.
  final Color muted;

  /// Hairlines and card borders.
  final Color line;

  /// The only hues left: muted, for status — never decoration.
  final Color ok;
  final Color warn;
  final Color danger;

  const Palette({
    required this.id,
    required this.label,
    required this.brightness,
    required this.base,
    required this.surface,
    required this.sunken,
    required this.ink,
    required this.muted,
    required this.line,
    required this.ok,
    required this.warn,
    required this.danger,
  });

  /// Text and icons drawn on an ink fill.
  Color get onInk => base;

  /// Faint text — hints, disabled.
  Color get faint => muted.withOpacity(0.85);   // 0.6 was ~2.6:1 on Plaster: unreadable at 11 px

  @override
  Palette copyWith() => this;

  @override
  Palette lerp(ThemeExtension<Palette>? other, double t) =>
      (other is Palette && t >= 0.5) ? other : this;
}

/// Day: lime-washed plaster, charcoal ink.
const kPlaster = Palette(
  id: 'plaster',
  label: 'Plaster',
  brightness: Brightness.light,
  base: Color(0xFFF3F0EA),
  surface: Color(0xFFFBFAF7),
  sunken: Color(0xFFE9E5DD),
  ink: Color(0xFF1A1917),
  muted: Color(0xFF6F6A62),
  line: Color(0xFFDCD6CB),
  ok: Color(0xFF4A7A58),
  warn: Color(0xFFA9781F),
  danger: Color(0xFFB0472F),
);

/// Night: charcoal walls, chalk ink.
const kCharcoal = Palette(
  id: 'charcoal',
  label: 'Charcoal',
  brightness: Brightness.dark,
  base: Color(0xFF141312),
  surface: Color(0xFF1D1C1A),
  sunken: Color(0xFF292724),
  ink: Color(0xFFEFEBE3),
  muted: Color(0xFF9C968C),
  line: Color(0xFF34312D),
  ok: Color(0xFF8DBA97),
  warn: Color(0xFFD9B26A),
  danger: Color(0xFFE08A72),
);

const List<Palette> kPalettes = [kPlaster, kCharcoal];

extension PaletteContext on BuildContext {
  /// The active palette. Reading it makes the widget rebuild on a switch.
  Palette get pal => Theme.of(this).extension<Palette>() ?? kPlaster;
}

/// Holds the active palette and persists the choice. UI preference only — no
/// app logic.
class ThemeController extends ChangeNotifier {
  static final ThemeController instance = ThemeController._();
  ThemeController._();

  static const _key = 'house_palette';
  Palette _palette = kPlaster;
  Palette get palette => _palette;

  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    final id = prefs.getString(_key);
    _palette = kPalettes.firstWhere((p) => p.id == id, orElse: () => kPlaster);
    notifyListeners();
  }

  Future<void> setPalette(Palette p) async {
    if (p.id == _palette.id) return;
    _palette = p;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_key, p.id);
  }
}

/// Material 3 theme for a palette: flat surfaces, hairline borders, ink for
/// every accent. No tint, no glow, no gradient.
ThemeData buildHouseTheme(Palette p) {
  final scheme = ColorScheme(
    brightness: p.brightness,
    primary: p.ink,
    onPrimary: p.onInk,
    primaryContainer: p.sunken,
    onPrimaryContainer: p.ink,
    secondary: p.muted,
    onSecondary: p.onInk,
    secondaryContainer: p.sunken,
    onSecondaryContainer: p.ink,
    tertiary: p.muted,
    onTertiary: p.onInk,
    error: p.danger,
    onError: p.onInk,
    errorContainer: p.danger.withOpacity(0.12),
    onErrorContainer: p.danger,
    surface: p.surface,
    onSurface: p.ink,
    onSurfaceVariant: p.muted,
    surfaceContainerLowest: p.base,
    surfaceContainerLow: p.surface,
    surfaceContainer: p.surface,
    surfaceContainerHigh: p.sunken,
    surfaceContainerHighest: p.sunken,
    outline: p.line,
    outlineVariant: p.line,
    inverseSurface: p.ink,
    onInverseSurface: p.onInk,
    inversePrimary: p.surface,
    shadow: Colors.black,
    scrim: Colors.black,
    surfaceTint: Colors.transparent,
  );

  final radius = BorderRadius.circular(14);
  final base = ThemeData(useMaterial3: true, brightness: p.brightness);
  final text = base.textTheme.apply(fontFamily: 'Roboto', bodyColor: p.ink, displayColor: p.ink);

  return base.copyWith(
    colorScheme: scheme,
    extensions: [p],
    scaffoldBackgroundColor: p.base,
    canvasColor: p.base,
    dividerColor: p.line,
    textTheme: text.copyWith(
      headlineMedium: text.headlineMedium
          ?.copyWith(fontWeight: FontWeight.w800, letterSpacing: -0.8),
      headlineSmall: text.headlineSmall
          ?.copyWith(fontWeight: FontWeight.w800, letterSpacing: -0.6),
      titleLarge: text.titleLarge?.copyWith(fontWeight: FontWeight.w700, letterSpacing: -0.3),
    ),
    iconTheme: IconThemeData(color: p.ink),
    dividerTheme: DividerThemeData(color: p.line, thickness: 1, space: 1),
    appBarTheme: AppBarTheme(
      backgroundColor: p.base,
      foregroundColor: p.ink,
      elevation: 0,
      scrolledUnderElevation: 0,
      surfaceTintColor: Colors.transparent,
      titleTextStyle: TextStyle(
          fontSize: 20, fontWeight: FontWeight.w700, color: p.ink, letterSpacing: -0.3),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: p.base,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      height: 68,
      indicatorColor: p.ink,
      indicatorShape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      iconTheme: WidgetStateProperty.resolveWith((s) => IconThemeData(
            color: s.contains(WidgetState.selected) ? p.onInk : p.muted,
          )),
      labelTextStyle: WidgetStateProperty.resolveWith((s) => TextStyle(
            fontSize: 11,
            fontWeight: s.contains(WidgetState.selected) ? FontWeight.w700 : FontWeight.w500,
            color: s.contains(WidgetState.selected) ? p.ink : p.muted,
          )),
    ),
    cardTheme: CardTheme(
      color: p.surface,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20), side: BorderSide(color: p.line)),
    ),
    listTileTheme: ListTileThemeData(iconColor: p.ink, textColor: p.ink),
    dialogTheme: DialogTheme(
      backgroundColor: p.surface,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(22), side: BorderSide(color: p.line)),
    ),
    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: p.surface,
      surfaceTintColor: Colors.transparent,
      modalBackgroundColor: p.surface,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
    ),
    popupMenuTheme: PopupMenuThemeData(
      color: p.surface,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(14), side: BorderSide(color: p.line)),
    ),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: p.ink,
      contentTextStyle: TextStyle(color: p.onInk),
      actionTextColor: p.onInk,
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(borderRadius: radius),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith(
          (s) => s.contains(WidgetState.selected) ? p.onInk : p.muted),
      trackColor: WidgetStateProperty.resolveWith(
          (s) => s.contains(WidgetState.selected) ? p.ink : p.sunken),
      trackOutlineColor: WidgetStateProperty.resolveWith(
          (s) => s.contains(WidgetState.selected) ? p.ink : p.line),
    ),
    sliderTheme: SliderThemeData(
      activeTrackColor: p.ink,
      inactiveTrackColor: p.sunken,
      thumbColor: p.ink,
      overlayColor: p.ink.withOpacity(0.08),
    ),
    progressIndicatorTheme: ProgressIndicatorThemeData(
      color: p.ink,
      linearTrackColor: p.sunken,
    ),
    chipTheme: ChipThemeData(
      backgroundColor: p.surface,
      selectedColor: p.ink,
      side: BorderSide(color: p.line),
      labelStyle: TextStyle(color: p.ink),
      secondaryLabelStyle: TextStyle(color: p.onInk),
      checkmarkColor: p.onInk,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: ButtonStyle(
        backgroundColor: WidgetStateProperty.resolveWith(
            (s) => s.contains(WidgetState.selected) ? p.ink : Colors.transparent),
        foregroundColor: WidgetStateProperty.resolveWith(
            (s) => s.contains(WidgetState.selected) ? p.onInk : p.ink),
        side: WidgetStatePropertyAll(BorderSide(color: p.line)),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: p.surface,
      labelStyle: TextStyle(color: p.muted),
      hintStyle: TextStyle(color: p.faint),
      prefixIconColor: p.muted,
      suffixIconColor: p.muted,
      border: OutlineInputBorder(borderRadius: radius, borderSide: BorderSide(color: p.line)),
      enabledBorder:
          OutlineInputBorder(borderRadius: radius, borderSide: BorderSide(color: p.line)),
      focusedBorder: OutlineInputBorder(
          borderRadius: radius, borderSide: BorderSide(color: p.ink, width: 1.6)),
      errorBorder:
          OutlineInputBorder(borderRadius: radius, borderSide: BorderSide(color: p.danger)),
      focusedErrorBorder: OutlineInputBorder(
          borderRadius: radius, borderSide: BorderSide(color: p.danger, width: 1.6)),
      contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(double.infinity, 52),
        backgroundColor: p.ink,
        foregroundColor: p.onInk,
        disabledBackgroundColor: p.sunken,
        disabledForegroundColor: p.muted,
        elevation: 0,
        shape: RoundedRectangleBorder(borderRadius: radius),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
      ),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: p.ink,
        foregroundColor: p.onInk,
        elevation: 0,
        shape: RoundedRectangleBorder(borderRadius: radius),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: p.ink,
        side: BorderSide(color: p.ink, width: 1.2),
        shape: RoundedRectangleBorder(borderRadius: radius),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(foregroundColor: p.ink),
    ),
    floatingActionButtonTheme: FloatingActionButtonThemeData(
      backgroundColor: p.ink,
      foregroundColor: p.onInk,
      elevation: 0,
      focusElevation: 0,
      hoverElevation: 0,
      highlightElevation: 0,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
    ),
  );
}
