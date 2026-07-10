import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// One selectable accent identity. Glassmorphism is the fixed brand; the accent
/// (toggle glow, highlights, and the aurora orbs behind the glass) is the user
/// variable. Three ship as presets; the layout is identical across them.
class AccentPreset {
  final String id;
  final String label;

  /// Primary accent — toggle glow, active highlights, key text.
  final Color accent;

  /// Base canvas behind everything (near-black, tinted per preset).
  final Color base;

  /// Radial "aurora" orbs painted behind the frosted glass, top→bottom.
  final List<Color> orbs;

  /// Whether the accent is bright enough that on-accent text should be dark.
  final bool accentIsLight;

  const AccentPreset({
    required this.id,
    required this.label,
    required this.accent,
    required this.base,
    required this.orbs,
    this.accentIsLight = false,
  });

  Color get onAccent => accentIsLight ? const Color(0xFF0A0A0A) : Colors.white;
}

const kAurora = AccentPreset(
  id: 'aurora',
  label: 'Aurora',
  accent: Color(0xFF22D3EE), // cyan
  base: Color(0xFF060A14),   // deeper navy-black
  orbs: [Color(0xFF7C3AED), Color(0xFF0EA5E9), Color(0xFF0D9488)],
  //      rich violet         bright blue          teal depth
);

const kObsidian = AccentPreset(
  id: 'obsidian',
  label: 'Obsidian',
  accent: Color(0xFFBEF264), // electric lime
  base: Color(0xFF0B0B0C),
  orbs: [Color(0xFF3F3F46), Color(0xFF1F2937), Color(0xFF4D7C0F)],
  accentIsLight: true,
);

const kSpectrum = AccentPreset(
  id: 'spectrum',
  label: 'Spectrum',
  accent: Color(0xFFF0569E), // magenta
  base: Color(0xFF140A17),
  orbs: [Color(0xFFC026D3), Color(0xFFEA580C), Color(0xFF4F46E5)],
);

const List<AccentPreset> kAccentPresets = [kAurora, kObsidian, kSpectrum];

/// Holds the active accent and persists the choice. UI preference only — no
/// app logic. Global singleton so any widget can rebuild on change.
class ThemeController extends ChangeNotifier {
  static final ThemeController instance = ThemeController._();
  ThemeController._();

  static const _key = 'accent_preset';
  AccentPreset _accent = kAurora;
  AccentPreset get accent => _accent;

  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    final id = prefs.getString(_key);
    _accent = kAccentPresets.firstWhere(
      (p) => p.id == id,
      orElse: () => kAurora,
    );
    notifyListeners();
  }

  Future<void> setAccent(AccentPreset preset) async {
    if (preset.id == _accent.id) return;
    _accent = preset;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_key, preset.id);
  }
}

/// Dark, glass-friendly Material 3 theme for the given accent. Surfaces are kept
/// transparent so the aurora and the package's backdrop blur read through.
ThemeData buildGlassTheme(AccentPreset a) {
  final scheme = ColorScheme.fromSeed(
    seedColor: a.accent,
    brightness: Brightness.dark,
  ).copyWith(
    primary: a.accent,
    surface: a.base,
    surfaceTint: Colors.transparent,
  );

  return ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    colorScheme: scheme,
    scaffoldBackgroundColor: Colors.transparent,
    fontFamily: 'Roboto',
    appBarTheme: const AppBarTheme(
      backgroundColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 0,
      surfaceTintColor: Colors.transparent,
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: Colors.transparent,
      elevation: 0,
      indicatorColor: a.accent.withOpacity(0.18),
      labelTextStyle: WidgetStatePropertyAll(
        TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: Colors.white.withOpacity(0.7)),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Colors.white.withOpacity(0.06),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: BorderSide.none,
      ),
      contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(double.infinity, 52),
        backgroundColor: a.accent,
        foregroundColor: a.onAccent,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
      ),
    ),
  );
}
