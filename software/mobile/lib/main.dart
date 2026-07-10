import 'package:flutter/material.dart';
import 'services/api_service.dart';
import 'services/voice_service.dart';
import 'services/voice_trigger.dart';
import 'theme/accents.dart';
import 'widgets/glass.dart';
import 'screens/login_screen.dart';
import 'screens/parent_shell.dart';
import 'screens/child_shell.dart';
import 'screens/onboarding_screen.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  VoiceTrigger.instance.init(); // listen for Quick Settings tile launches
  await VoiceService.loadSettings(); // restore voice language + Groq settings
  await ThemeController.instance.load();
  runApp(const MayaSmartHomeApp());
}

class MayaSmartHomeApp extends StatelessWidget {
  const MayaSmartHomeApp({super.key});

  @override
  Widget build(BuildContext context) {
    // Rebuild the whole app when the user switches accent. Dark-only:
    // glassmorphism is the fixed brand, the accent is the variable.
    return ListenableBuilder(
      listenable: ThemeController.instance,
      builder: (context, _) {
        final accent = ThemeController.instance.accent;
        return MaterialApp(
          title: 'Maya Smart Home',
          navigatorKey: VoiceTrigger.navigatorKey,
          debugShowCheckedModeBanner: false,
          theme: buildGlassTheme(accent),
          darkTheme: buildGlassTheme(accent),
          themeMode: ThemeMode.dark,
          // Paint the aurora canvas behind every screen so the frosted glass
          // surfaces have something to blur over.
          builder: (context, child) => AuroraBackground(
            accent: accent,
            child: child ?? const SizedBox.shrink(),
          ),
          // Named route for OnboardingScreen to navigate back to
          routes: {
            '/': (_) => const _AuthGate(),
          },
        );
      },
    );
  }
}

/// Checks saved credentials on startup and routes to the correct shell.
class _AuthGate extends StatefulWidget {
  const _AuthGate();

  @override
  State<_AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<_AuthGate> {
  bool _checking = true;

  @override
  void initState() {
    super.initState();
    _checkAuth();
  }

  Future<void> _checkAuth() async {
    await ApiService.init();

    if (!mounted) return;

    if (ApiService.isLoggedIn) {
      // Validate the token is still valid
      try {
        final profile = await ApiService.getProfile();
        final role = profile['role'] ?? 'parent';
        final isChild = role == 'child';

        await ApiService.saveCredentials(
          jwtToken: ApiService.token,
          house: profile['house_id'],
          name: profile['name'] ?? ApiService.userName,
          role: role,
          accountId: profile['acc_id'],
          child: isChild,
        );

        if (!mounted) return;

        // For children, go straight to shell (they're locked to one house)
        if (isChild) {
          Navigator.pushReplacement(
            context,
            MaterialPageRoute(builder: (_) => const ChildShell()),
          );
          return;
        }

        // For parents, fetch houses and decide
        try {
          await ApiService.getHouses();
        } catch (_) {
          // If houses fetch fails, still proceed with whatever we have
        }

        if (!mounted) return;

        if (ApiService.houses.isEmpty) {
          // No houses → show onboarding
          Navigator.pushReplacement(
            context,
            MaterialPageRoute(builder: (_) => const OnboardingScreen()),
          );
        } else {
          Navigator.pushReplacement(
            context,
            MaterialPageRoute(builder: (_) => const ParentShell()),
          );
        }
      } catch (_) {
        // Token expired or invalid, go to login
        await ApiService.logout();
        if (!mounted) return;
        setState(() => _checking = false);
      }
    } else {
      setState(() => _checking = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_checking) {
      return Scaffold(
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(20),
                child: Image.asset('assets/brand/maya_logo.png',
                    width: 84, height: 84, fit: BoxFit.cover),
              ),
              const SizedBox(height: 16),
              const CircularProgressIndicator(),
              const SizedBox(height: 16),
              Text(
                'Maya Smart Home',
                style: Theme.of(context).textTheme.titleLarge?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
              ),
            ],
          ),
        ),
      );
    }
    return const LoginScreen();
  }
}
