import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../services/api_service.dart';

/// Login screen with a Parent/Child toggle.
/// Parent: email + password.  Child: ID + PIN.
/// "Register" link opens the web portal in the system browser.
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen>
    with SingleTickerProviderStateMixin {
  // 0 = Parent, 1 = Child
  int _mode = 0;
  bool _loading = false;

  // Parent controllers
  final _emailCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  bool _obscurePass = true;

  // Child controllers
  final _childIdCtrl = TextEditingController();
  final _pinCtrl = TextEditingController();
  bool _obscurePin = true;

  @override
  void dispose() {
    _emailCtrl.dispose();
    _passCtrl.dispose();
    _childIdCtrl.dispose();
    _pinCtrl.dispose();
    super.dispose();
  }

  // ── Parent Login ───────────────────────────────────────────────
  Future<void> _loginParent() async {
    final email = _emailCtrl.text.trim();
    final password = _passCtrl.text;
    if (email.isEmpty || password.isEmpty) {
      _snack('Please fill in all fields');
      return;
    }

    setState(() => _loading = true);
    try {
      final data = await ApiService.login(email, password);
      final token = data['token'] as String;

      // Fetch full profile to get house_id, role, etc.
      ApiService.token = token;
      final profile = await ApiService.getProfile();

      await ApiService.saveCredentials(
        jwtToken: token,
        house: profile['house_id'],
        name: profile['name'] ?? email,
        role: profile['role'] ?? 'parent',
        accountId: profile['acc_id'],
        child: false,
      );

      if (!mounted) return;
      // Navigate to AuthGate which handles house check & routing
      Navigator.pushNamedAndRemoveUntil(context, '/', (_) => false);
    } catch (e) {
      _snack(e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  // ── Child Login ────────────────────────────────────────────────
  Future<void> _loginChild() async {
    final idText = _childIdCtrl.text.trim();
    final pin = _pinCtrl.text.trim();
    if (idText.isEmpty || pin.isEmpty) {
      _snack('Please fill in all fields');
      return;
    }
    final childId = int.tryParse(idText);
    if (childId == null) {
      _snack('Child ID must be a number');
      return;
    }

    setState(() => _loading = true);
    try {
      final data = await ApiService.childLogin(childId, pin);
      final token = data['token'] as String;

      // Fetch full profile
      ApiService.token = token;
      final profile = await ApiService.getProfile();

      await ApiService.saveCredentials(
        jwtToken: token,
        house: profile['house_id'],
        name: profile['name'] ?? 'Child',
        role: 'child',
        accountId: profile['acc_id'],
        child: true,
      );

      if (!mounted) return;
      // Navigate to AuthGate which handles routing
      Navigator.pushNamedAndRemoveUntil(context, '/', (_) => false);
    } catch (e) {
      _snack(e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  // ── Open Registration on Web ───────────────────────────────────
  Future<void> _openWebRegistration() async {
    final uri = Uri.parse('${ApiService.baseUrl}');
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    } else {
      _snack('Could not open browser');
    }
  }

  void _snack(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..clearSnackBars()
      ..showSnackBar(SnackBar(
        content: Text(msg),
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ));
  }

  // ── Build ──────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                // ── Logo ─────────────────────────────────────────
                Container(
                  width: 72,
                  height: 72,
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      colors: [cs.primary, cs.tertiary],
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                    ),
                    borderRadius: BorderRadius.circular(20),
                    boxShadow: [
                      BoxShadow(
                        color: cs.primary.withOpacity(0.35),
                        blurRadius: 24,
                        offset: const Offset(0, 8),
                      ),
                    ],
                  ),
                  child: const Icon(Icons.bolt_rounded,
                      size: 40, color: Colors.white),
                ),
                const SizedBox(height: 20),
                Text('Maya Smart Home',
                    style: tt.headlineMedium
                        ?.copyWith(fontWeight: FontWeight.w800)),
                const SizedBox(height: 4),
                Text('Control your home, anywhere.',
                    style: tt.bodyMedium
                        ?.copyWith(color: cs.onSurfaceVariant)),
                const SizedBox(height: 36),

                // ── Mode Toggle ──────────────────────────────────
                SegmentedButton<int>(
                  segments: const [
                    ButtonSegment(
                      value: 0,
                      label: Text('Parent'),
                      icon: Icon(Icons.person_rounded),
                    ),
                    ButtonSegment(
                      value: 1,
                      label: Text('Child'),
                      icon: Icon(Icons.child_care_rounded),
                    ),
                  ],
                  selected: {_mode},
                  onSelectionChanged: (v) => setState(() => _mode = v.first),
                  showSelectedIcon: false,
                  style: ButtonStyle(
                    shape: WidgetStatePropertyAll(
                      RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(14)),
                    ),
                  ),
                ),
                const SizedBox(height: 28),

                // ── Form ─────────────────────────────────────────
                AnimatedSwitcher(
                  duration: const Duration(milliseconds: 300),
                  child: _mode == 0 ? _parentForm(cs) : _childForm(cs),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  // ── Parent Form ────────────────────────────────────────────────
  Widget _parentForm(ColorScheme cs) {
    return Column(
      key: const ValueKey('parent'),
      children: [
        TextField(
          controller: _emailCtrl,
          keyboardType: TextInputType.emailAddress,
          textInputAction: TextInputAction.next,
          decoration: const InputDecoration(
            labelText: 'Email Address',
            prefixIcon: Icon(Icons.email_outlined),
          ),
        ),
        const SizedBox(height: 16),
        TextField(
          controller: _passCtrl,
          obscureText: _obscurePass,
          textInputAction: TextInputAction.done,
          onSubmitted: (_) => _loginParent(),
          decoration: InputDecoration(
            labelText: 'Password',
            prefixIcon: const Icon(Icons.lock_outline_rounded),
            suffixIcon: IconButton(
              icon: Icon(
                  _obscurePass ? Icons.visibility_off : Icons.visibility),
              onPressed: () =>
                  setState(() => _obscurePass = !_obscurePass),
            ),
          ),
        ),
        const SizedBox(height: 24),
        FilledButton(
          onPressed: _loading ? null : _loginParent,
          child: _loading
              ? const SizedBox(
                  width: 22,
                  height: 22,
                  child: CircularProgressIndicator(
                      strokeWidth: 2.5, color: Colors.white),
                )
              : const Text('Sign In'),
        ),
        const SizedBox(height: 20),
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text("Don't have an account? ",
                style: TextStyle(color: cs.onSurfaceVariant)),
            GestureDetector(
              onTap: _openWebRegistration,
              child: Text(
                'Register on Web',
                style: TextStyle(
                  color: cs.primary,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            Icon(Icons.open_in_new_rounded,
                size: 14, color: cs.primary),
          ],
        ),
      ],
    );
  }

  // ── Child Form ─────────────────────────────────────────────────
  Widget _childForm(ColorScheme cs) {
    return Column(
      key: const ValueKey('child'),
      children: [
        TextField(
          controller: _childIdCtrl,
          keyboardType: TextInputType.number,
          textInputAction: TextInputAction.next,
          decoration: const InputDecoration(
            labelText: 'Child Account ID',
            prefixIcon: Icon(Icons.badge_outlined),
            helperText: 'Ask your parents for your Child ID number.',
          ),
        ),
        const SizedBox(height: 16),
        TextField(
          controller: _pinCtrl,
          obscureText: _obscurePin,
          keyboardType: TextInputType.number,
          maxLength: 4,
          textInputAction: TextInputAction.done,
          onSubmitted: (_) => _loginChild(),
          decoration: InputDecoration(
            labelText: '4-Digit Security PIN',
            prefixIcon: const Icon(Icons.pin_outlined),
            counterText: '',
            suffixIcon: IconButton(
              icon:
                  Icon(_obscurePin ? Icons.visibility_off : Icons.visibility),
              onPressed: () =>
                  setState(() => _obscurePin = !_obscurePin),
            ),
          ),
        ),
        const SizedBox(height: 24),
        FilledButton(
          onPressed: _loading ? null : _loginChild,
          child: _loading
              ? const SizedBox(
                  width: 22,
                  height: 22,
                  child: CircularProgressIndicator(
                      strokeWidth: 2.5, color: Colors.white),
                )
              : const Text('Access Dashboard'),
        ),
      ],
    );
  }
}
