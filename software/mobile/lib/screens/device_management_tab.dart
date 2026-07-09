import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../services/api_service.dart';
import '../widgets/glass.dart';
import 'provision_screen.dart';

/// Device management tab — view device details and register new devices.
/// "Provision" opens the BLE provisioning screen.
/// "Register" links the device to the household via REST API.
class DeviceManagementTab extends StatefulWidget {
  const DeviceManagementTab({super.key});

  @override
  State<DeviceManagementTab> createState() => _DeviceManagementTabState();
}

class _DeviceManagementTabState extends State<DeviceManagementTab>
    with AutomaticKeepAliveClientMixin {
  List<dynamic> _devices = [];
  bool _loading = true;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _fetchDevices();
  }

  Future<void> _fetchDevices() async {
    try {
      final devices = await ApiService.getDevices();
      if (mounted) {
        setState(() {
          _devices = devices;
          _loading = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  // ── Open the web marketplace in the browser ────────────────────
  Future<void> _openWebStore() async {
    final uri = Uri.parse('${ApiService.baseUrl}/store');
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    } else if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('Could not open browser'),
        behavior: SnackBarBehavior.floating,
      ));
    }
  }

  // ── Open BLE Provisioning ──────────────────────────────────────
  Future<void> _openProvision() async {
    await Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => const ProvisionScreen()),
    );
    _fetchDevices(); // Refresh after returning
  }

  String _formatUptime(dynamic ms) {
    if (ms == null) return '—';
    final secs = (ms as num).toInt() ~/ 1000;
    final m = secs ~/ 60;
    final h = m ~/ 60;
    if (h > 0) return '${h}h ${m % 60}m';
    if (m > 0) return '${m}m ${secs % 60}s';
    return '${secs}s';
  }

  // ── Build ──────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    super.build(context);
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;

    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }

    return RefreshIndicator(
      onRefresh: _fetchDevices,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Action buttons — adding devices requires master (or granted) rights
          if (ApiService.canManageDevices) ...[
            FilledButton.icon(
              onPressed: _openProvision,
              icon: const Icon(Icons.bluetooth_connected_rounded),
              label: const Text('Register New Device'),
            ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: _openWebStore,
              icon: const Icon(Icons.storefront_outlined),
              label: const Text('Buy Devices'),
            ),
          ] else
            GlassSurface(
              padding: const EdgeInsets.all(14),
              child: Row(
                children: [
                  Icon(Icons.lock_outline_rounded,
                      size: 20, color: cs.onSurfaceVariant),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      'Only the house owner (or members they authorize) can add or remove devices.',
                      style: tt.bodySmall
                          ?.copyWith(color: cs.onSurfaceVariant),
                    ),
                  ),
                ],
              ),
            ),
          const SizedBox(height: 20),

          // Section header
          Text('Registered Devices',
              style: tt.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),

          if (_devices.isEmpty)
            GlassSurface(
              padding: const EdgeInsets.all(32),
              child: Column(
                children: [
                  Icon(Icons.devices_other_rounded,
                      size: 48,
                      color: cs.onSurfaceVariant.withOpacity(0.3)),
                  const SizedBox(height: 12),
                  Text('No devices registered yet',
                      style: tt.bodyMedium
                          ?.copyWith(color: cs.onSurfaceVariant)),
                  const SizedBox(height: 4),
                  Text(
                    'Register a new Maya Smart Home device via BLE.',
                    style: tt.bodySmall
                        ?.copyWith(color: cs.onSurfaceVariant),
                    textAlign: TextAlign.center,
                  ),
                ],
              ),
            )
          else
            ..._devices.map((d) => _detailCard(d, cs, tt)),
        ],
      ),
    );
  }

  // ── Device Detail Card ─────────────────────────────────────────
  Widget _detailCard(dynamic device, ColorScheme cs, TextTheme tt) {
    final online = device['online'] == true;
    final ch1 = device['ch1'] ?? 'off';
    final ch2 = device['ch2'] ?? 'off';
    final ch3 = device['ch3'] ?? 'off';

    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: GlassSurface(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.settings_remote_rounded,
                    color: cs.primary, size: 24),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(device['name'] ?? 'Unnamed Device',
                      style:
                          tt.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
                ),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: online
                        ? Colors.green.withOpacity(0.12)
                        : cs.error.withOpacity(0.12),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Text(
                    online ? 'Online' : 'Offline',
                    style: tt.labelSmall?.copyWith(
                      fontWeight: FontWeight.w700,
                      color: online ? Colors.green : cs.error,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 14),
            _infoRow('Device ID', device['device_id'] ?? '—', cs, tt),
            _infoRow('IP Address', device['ip'] ?? '—', cs, tt),
            _infoRow('Uptime', _formatUptime(device['last_uptime_ms']), cs, tt),
            _infoRow(
              'Channels',
              'CH1: $ch1 • CH2: $ch2 • CH3: $ch3',
              cs,
              tt,
            ),
          ],
        ),
      ),
    );
  }

  Widget _infoRow(
      String label, String value, ColorScheme cs, TextTheme tt) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        children: [
          SizedBox(
            width: 90,
            child: Text(label,
                style: tt.labelSmall
                    ?.copyWith(color: cs.onSurfaceVariant)),
          ),
          Expanded(
            child: Text(value,
                style: tt.bodySmall?.copyWith(
                    fontWeight: FontWeight.w600,
                    fontFamily: label == 'Device ID' ? 'monospace' : null)),
          ),
        ],
      ),
    );
  }
}
