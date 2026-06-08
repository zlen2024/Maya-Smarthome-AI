import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import '../services/api_service.dart';

/// Full-screen onboarding for users with no houses.
/// Lets them create a new house or join an existing one.
class OnboardingScreen extends StatelessWidget {
  const OnboardingScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 32),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                // ── Illustration ─────────────────────────────────
                Container(
                  width: 88,
                  height: 88,
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      colors: [cs.primary, cs.tertiary],
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                    ),
                    borderRadius: BorderRadius.circular(24),
                    boxShadow: [
                      BoxShadow(
                        color: cs.primary.withOpacity(0.35),
                        blurRadius: 28,
                        offset: const Offset(0, 10),
                      ),
                    ],
                  ),
                  child: const Icon(Icons.home_rounded,
                      size: 48, color: Colors.white),
                ),
                const SizedBox(height: 24),

                Text(
                  'Welcome to Maya!',
                  style:
                      tt.headlineMedium?.copyWith(fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 8),
                Text(
                  'Get started by creating your smart home\nor joining an existing one.',
                  textAlign: TextAlign.center,
                  style:
                      tt.bodyMedium?.copyWith(color: cs.onSurfaceVariant),
                ),
                const SizedBox(height: 40),

                // ── Create House Card ────────────────────────────
                _ActionCard(
                  icon: Icons.add_home_rounded,
                  emoji: '🏠',
                  title: 'Create a House',
                  subtitle: 'Set up a new smart home',
                  color: cs.primary,
                  onTap: () => _showCreateDialog(context),
                ),
                const SizedBox(height: 16),

                // ── Join House Card ──────────────────────────────
                _ActionCard(
                  icon: Icons.link_rounded,
                  emoji: '🔗',
                  title: 'Join a House',
                  subtitle: 'Scan QR or enter invite code',
                  color: cs.tertiary,
                  onTap: () => _showJoinDialog(context),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  // ── Create House Dialog ──────────────────────────────────────────
  void _showCreateDialog(BuildContext context) {
    final controller = TextEditingController();

    bool loading = false;

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          title: const Text('Create a House'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: controller,
                autofocus: true,
                textCapitalization: TextCapitalization.words,
                decoration: const InputDecoration(
                  labelText: 'Location / House Name',
                  prefixIcon: Icon(Icons.location_on_outlined),
                  hintText: 'e.g. My Home, Office',
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: loading ? null : () => Navigator.pop(ctx),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: loading
                  ? null
                  : () async {
                      final location = controller.text.trim();
                      if (location.isEmpty) return;
                      setDialogState(() => loading = true);
                      try {
                        await ApiService.createHouse(location);
                        if (ctx.mounted) Navigator.pop(ctx);
                        if (context.mounted) _navigateToAuthGate(context);
                      } catch (e) {
                        setDialogState(() => loading = false);
                        if (ctx.mounted) {
                          ScaffoldMessenger.of(ctx).showSnackBar(SnackBar(
                            content: Text(e
                                .toString()
                                .replaceFirst('Exception: ', '')),
                            behavior: SnackBarBehavior.floating,
                          ));
                        }
                      }
                    },
              child: loading
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: Colors.white),
                    )
                  : const Text('Create'),
            ),
          ],
        ),
      ),
    );
  }

  // ── Join House Dialog ────────────────────────────────────────────
  void _showJoinDialog(BuildContext context) {
    final houseIdCtrl = TextEditingController();
    final pinCtrl = TextEditingController();
    bool loading = false;

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          title: const Text('Join a House'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              // Scan QR Button
              FilledButton.icon(
                onPressed: loading
                    ? null
                    : () {
                        Navigator.pop(ctx);
                        _openQrScanner(context);
                      },
                icon: const Icon(Icons.qr_code_scanner_rounded),
                label: const Text('Scan QR Code'),
                style: FilledButton.styleFrom(
                  minimumSize: const Size(double.infinity, 48),
                ),
              ),
              const SizedBox(height: 20),
              Row(
                children: [
                  const Expanded(child: Divider()),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 12),
                    child: Text('OR',
                        style: Theme.of(ctx).textTheme.labelSmall?.copyWith(
                              color: Theme.of(ctx)
                                  .colorScheme
                                  .onSurfaceVariant,
                            )),
                  ),
                  const Expanded(child: Divider()),
                ],
              ),
              const SizedBox(height: 20),
              // Manual entry
              TextField(
                controller: houseIdCtrl,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'House ID',
                  prefixIcon: Icon(Icons.tag_rounded),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: pinCtrl,
                keyboardType: TextInputType.number,
                maxLength: 6,
                decoration: const InputDecoration(
                  labelText: '6-Digit PIN',
                  prefixIcon: Icon(Icons.pin_outlined),
                  counterText: '',
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: loading ? null : () => Navigator.pop(ctx),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: loading
                  ? null
                  : () async {
                      final id = int.tryParse(houseIdCtrl.text.trim());
                      final pin = pinCtrl.text.trim();
                      if (id == null || pin.length != 6) {
                        ScaffoldMessenger.of(ctx).showSnackBar(const SnackBar(
                          content: Text(
                              'Enter a valid House ID and 6-digit PIN'),
                          behavior: SnackBarBehavior.floating,
                        ));
                        return;
                      }
                      setDialogState(() => loading = true);
                      try {
                        await ApiService.joinHouse(id, pin);
                        if (ctx.mounted) Navigator.pop(ctx);
                        if (context.mounted) _navigateToAuthGate(context);
                      } catch (e) {
                        setDialogState(() => loading = false);
                        if (ctx.mounted) {
                          ScaffoldMessenger.of(ctx).showSnackBar(SnackBar(
                            content: Text(e
                                .toString()
                                .replaceFirst('Exception: ', '')),
                            behavior: SnackBarBehavior.floating,
                          ));
                        }
                      }
                    },
              child: loading
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: Colors.white),
                    )
                  : const Text('Join'),
            ),
          ],
        ),
      ),
    );
  }

  // ── QR Scanner ───────────────────────────────────────────────────
  void _openQrScanner(BuildContext context) {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => _QrScannerPage(
          onScanned: (houseId, pin) async {
            Navigator.pop(context); // Close scanner
            try {
              await ApiService.joinHouse(houseId, pin);
              if (context.mounted) _navigateToAuthGate(context);
            } catch (e) {
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                  content:
                      Text(e.toString().replaceFirst('Exception: ', '')),
                  behavior: SnackBarBehavior.floating,
                ));
              }
            }
          },
        ),
      ),
    );
  }

  void _navigateToAuthGate(BuildContext context) {
    // Push to the root AuthGate to re-evaluate state
    Navigator.pushNamedAndRemoveUntil(context, '/', (_) => false);
  }
}

// ── Action Card Widget ─────────────────────────────────────────────
class _ActionCard extends StatelessWidget {
  final IconData icon;
  final String emoji;
  final String title;
  final String subtitle;
  final Color color;
  final VoidCallback onTap;

  const _ActionCard({
    required this.icon,
    required this.emoji,
    required this.title,
    required this.subtitle,
    required this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;

    return Card(
      color: cs.surfaceContainerLow,
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Row(
            children: [
              Container(
                width: 56,
                height: 56,
                decoration: BoxDecoration(
                  color: color.withOpacity(0.12),
                  borderRadius: BorderRadius.circular(16),
                ),
                child: Center(
                  child: Text(emoji,
                      style: const TextStyle(fontSize: 28)),
                ),
              ),
              const SizedBox(width: 20),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title,
                        style: tt.titleMedium
                            ?.copyWith(fontWeight: FontWeight.w700)),
                    const SizedBox(height: 4),
                    Text(subtitle,
                        style: tt.bodySmall
                            ?.copyWith(color: cs.onSurfaceVariant)),
                  ],
                ),
              ),
              Icon(Icons.chevron_right_rounded,
                  color: cs.onSurfaceVariant),
            ],
          ),
        ),
      ),
    );
  }
}

// ── QR Scanner Page ────────────────────────────────────────────────
class _QrScannerPage extends StatefulWidget {
  final Future<void> Function(int houseId, String pin) onScanned;

  const _QrScannerPage({required this.onScanned});

  @override
  State<_QrScannerPage> createState() => _QrScannerPageState();
}

class _QrScannerPageState extends State<_QrScannerPage> {
  bool _processed = false;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Scan Invite QR')),
      body: MobileScanner(
        onDetect: (capture) {
          if (_processed) return;
          final barcode = capture.barcodes.firstOrNull;
          if (barcode?.rawValue == null) return;

          try {
            final data =
                jsonDecode(barcode!.rawValue!) as Map<String, dynamic>;
            final houseId = data['house_id'] as int;
            final pin = data['pin'] as String;
            _processed = true;
            widget.onScanned(houseId, pin);
          } catch (_) {
            if (mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text('Invalid QR code'),
                  behavior: SnackBarBehavior.floating,
                ),
              );
            }
          }
        },
      ),
    );
  }
}
