import 'dart:async';
import 'package:flutter/material.dart';
import '../services/api_service.dart';

/// Main device dashboard showing all devices with inline channel toggles.
/// For child users, only permitted channels are interactive.
class DevicesTab extends StatefulWidget {
  const DevicesTab({super.key});

  @override
  State<DevicesTab> createState() => _DevicesTabState();
}

class _DevicesTabState extends State<DevicesTab>
    with AutomaticKeepAliveClientMixin {
  List<dynamic> _devices = [];
  List<dynamic> _relays = [];
  List<dynamic> _permissions = [];
  bool _loading = true;
  String? _error;
  StreamSubscription? _broadcastSub;
  Timer? _pollTimer;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _fetchAll();

    // Listen for real-time WebSocket updates
    _broadcastSub = ApiService.broadcasts.listen(_handleBroadcast);

    // Periodic polling as backup (every 10s)
    _pollTimer = Timer.periodic(const Duration(seconds: 10), (_) => _fetchAll());
  }

  @override
  void dispose() {
    _broadcastSub?.cancel();
    _pollTimer?.cancel();
    super.dispose();
  }

  // ── Data Fetching ──────────────────────────────────────────────
  Future<void> _fetchAll() async {
    try {
      final devices = await ApiService.getDevices();

      // Fetch relays + permissions for child filtering
      List<dynamic> relays = [];
      List<dynamic> perms = [];
      try {
        relays = await ApiService.getRelays();
      } catch (_) {}

      if (ApiService.isChild) {
        try {
          perms = await ApiService.getPermissions(childId: ApiService.accId);
        } catch (_) {}
      } else {
        try {
          perms = await ApiService.getPermissions();
        } catch (_) {}
      }

      if (mounted) {
        setState(() {
          _devices = devices;
          _relays = relays;
          _permissions = perms;
          _loading = false;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = e.toString().replaceFirst('Exception: ', '');
        });
      }
    }
  }

  // ── WebSocket Broadcast Handler ────────────────────────────────
  void _handleBroadcast(Map<String, dynamic> data) {
    final type = data['type'];
    final deviceId = data['device_id'];
    if (deviceId == null) return;

    setState(() {
      final idx = _devices.indexWhere((d) => d['device_id'] == deviceId);
      if (idx == -1) return;

      if (type == 'device_update') {
        _devices[idx]['ch1'] = data['ch1'];
        _devices[idx]['ch2'] = data['ch2'];
        _devices[idx]['ch3'] = data['ch3'];
        _devices[idx]['online'] = true;
      } else if (type == 'device_offline') {
        _devices[idx]['online'] = false;
      }
    });
  }

  // ── Channel name / relay lookup ────────────────────────────────
  Map<String, dynamic>? _relayFor(String deviceId, int channelNum) {
    for (final r in _relays) {
      if (r['device_id'] == deviceId && r['channel_number'] == channelNum) {
        return Map<String, dynamic>.from(r as Map);
      }
    }
    return null;
  }

  String _channelName(String deviceId, int channelNum) {
    final r = _relayFor(deviceId, channelNum);
    final name = r?['name'] as String?;
    return (name == null || name.isEmpty) ? 'Channel $channelNum' : name;
  }

  Future<void> _renameChannel(String deviceId, int channelNum) async {
    final relay = _relayFor(deviceId, channelNum);
    if (relay == null) return;
    final ctrl = TextEditingController(text: _channelName(deviceId, channelNum));
    final newName = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Rename channel $channelNum'),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          maxLength: 40,
          textCapitalization: TextCapitalization.words,
          decoration: const InputDecoration(
            labelText: 'Channel name',
            hintText: 'e.g. Television',
            counterText: '',
          ),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, ctrl.text.trim()),
            child: const Text('Save'),
          ),
        ],
      ),
    );
    if (newName == null || newName.isEmpty) return;
    try {
      await ApiService.renameRelay(relay['relay_id'] as int, newName);
      await _fetchAll();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(e.toString().replaceFirst('Exception: ', '')),
          behavior: SnackBarBehavior.floating,
        ));
      }
    }
  }

  // ── Channel Permission Check ───────────────────────────────────
  bool _isChannelAllowed(String deviceId, int channelNum) {
    if (!ApiService.isChild) return true;

    final relay = _relays.firstWhere(
      (r) => r['device_id'] == deviceId && r['channel_number'] == channelNum,
      orElse: () => null,
    );
    if (relay == null) return false;

    final perm = _permissions.firstWhere(
      (p) => p['relay_id'] == relay['relay_id'],
      orElse: () => null,
    );
    return perm != null && perm['is_allowed'] == true;
  }

  // ── Remove Device ──────────────────────────────────────────────
  Future<void> _removeDevice(String deviceId, String name) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Remove device?'),
        content: Text(
            '"$name" will be removed from this house and the device itself '
            'will be wiped back to setup mode. You can re-register it later '
            'via Bluetooth provisioning.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(ctx).colorScheme.error,
            ),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Remove'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    try {
      await ApiService.deleteDevice(deviceId);
      setState(() {
        _devices.removeWhere((d) => d['device_id'] == deviceId);
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Device removed — it has been reset to setup mode'),
          behavior: SnackBarBehavior.floating,
        ));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(e.toString().replaceFirst('Exception: ', '')),
          behavior: SnackBarBehavior.floating,
        ));
      }
    }
  }

  // ── Toggle Channel ─────────────────────────────────────────────
  Future<void> _toggleChannel(
      String deviceId, int channel, bool newState) async {
    final cmd = newState ? 'output_on' : 'output_off';

    // Optimistic update
    setState(() {
      final idx = _devices.indexWhere((d) => d['device_id'] == deviceId);
      if (idx != -1) {
        _devices[idx]['ch$channel'] = newState ? 'on' : 'off';
      }
    });

    try {
      await ApiService.sendCommand(deviceId, cmd, channel: channel);
    } catch (e) {
      // Revert on failure
      setState(() {
        final idx = _devices.indexWhere((d) => d['device_id'] == deviceId);
        if (idx != -1) {
          _devices[idx]['ch$channel'] = newState ? 'off' : 'on';
        }
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(e.toString().replaceFirst('Exception: ', '')),
          behavior: SnackBarBehavior.floating,
        ));
      }
    }
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

    if (_error != null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline_rounded, size: 48,
                color: cs.error),
            const SizedBox(height: 12),
            Text(_error!, style: tt.bodyMedium),
            const SizedBox(height: 16),
            FilledButton.tonal(
              onPressed: () {
                setState(() => _loading = true);
                _fetchAll();
              },
              child: const Text('Retry'),
            ),
          ],
        ),
      );
    }

    if (_devices.isEmpty) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.sensors_off_rounded, size: 56,
                color: cs.onSurfaceVariant.withOpacity(0.35)),
            const SizedBox(height: 12),
            Text('No devices connected',
                style: tt.titleMedium?.copyWith(
                    color: cs.onSurfaceVariant)),
            const SizedBox(height: 4),
            Text(
              ApiService.isChild
                  ? 'Ask your parent to register devices.'
                  : 'Go to the Device tab to provision a new device.',
              style: tt.bodySmall?.copyWith(color: cs.onSurfaceVariant),
              textAlign: TextAlign.center,
            ),
          ],
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: _fetchAll,
      child: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: _devices.length,
        itemBuilder: (ctx, i) => _deviceCard(_devices[i], cs, tt),
      ),
    );
  }

  // ── Device Card ────────────────────────────────────────────────
  Widget _deviceCard(
      dynamic device, ColorScheme cs, TextTheme tt) {
    final deviceId = device['device_id'] as String;
    final name = device['name'] ?? deviceId;
    final online = device['online'] == true;

    const channelColors = [
      Color(0xFFEF4444), // CH1 red
      Color(0xFF10B981), // CH2 green
      Color(0xFF3B82F6), // CH3 blue
    ];

    return Card(
      margin: const EdgeInsets.only(bottom: 14),
      color: cs.surfaceContainerLow,
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Header row
            Row(
              children: [
                Icon(Icons.electrical_services_rounded,
                    color: cs.primary, size: 26),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(name,
                          style: tt.titleSmall
                              ?.copyWith(fontWeight: FontWeight.w700)),
                      Text(deviceId,
                          style: tt.labelSmall?.copyWith(
                              color: cs.onSurfaceVariant,
                              fontFamily: 'monospace')),
                    ],
                  ),
                ),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: online
                        ? Colors.green.withOpacity(0.12)
                        : cs.error.withOpacity(0.12),
                    borderRadius: BorderRadius.circular(20),
                    border: Border.all(
                      color: online
                          ? Colors.green.withOpacity(0.3)
                          : cs.error.withOpacity(0.3),
                    ),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        width: 7,
                        height: 7,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: online ? Colors.green : cs.error,
                        ),
                      ),
                      const SizedBox(width: 5),
                      Text(
                        online ? 'Online' : 'Offline',
                        style: tt.labelSmall?.copyWith(
                          fontWeight: FontWeight.w700,
                          color: online ? Colors.green : cs.error,
                        ),
                      ),
                    ],
                  ),
                ),
                if (ApiService.canManageDevices)
                  PopupMenuButton<String>(
                    icon: Icon(Icons.more_vert_rounded,
                        size: 20, color: cs.onSurfaceVariant),
                    onSelected: (v) {
                      if (v == 'remove') _removeDevice(deviceId, name);
                    },
                    itemBuilder: (ctx) => [
                      PopupMenuItem(
                        value: 'remove',
                        child: Row(
                          children: [
                            Icon(Icons.delete_outline_rounded,
                                size: 18, color: cs.error),
                            const SizedBox(width: 8),
                            Text('Remove device',
                                style: TextStyle(color: cs.error)),
                          ],
                        ),
                      ),
                    ],
                  ),
              ],
            ),
            const SizedBox(height: 16),

            // Channel toggles
            for (int ch = 1; ch <= 3; ch++)
              _channelRow(device, ch, channelColors[ch - 1], cs, tt, online),
          ],
        ),
      ),
    );
  }

  Widget _channelRow(dynamic device, int ch, Color color, ColorScheme cs,
      TextTheme tt, bool online) {
    final deviceId = device['device_id'] as String;
    final state = device['ch$ch'];
    final isOn = state == 'on';
    final allowed = _isChannelAllowed(deviceId, ch);
    final enabled = online && allowed;

    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 4),
      decoration: BoxDecoration(
        color: cs.surfaceContainerHighest.withOpacity(0.5),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Row(
        children: [
          Container(
            width: 10,
            height: 10,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: isOn ? color : cs.onSurfaceVariant.withOpacity(0.25),
              boxShadow: isOn
                  ? [BoxShadow(color: color.withOpacity(0.5), blurRadius: 8)]
                  : null,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: GestureDetector(
              onTap: ApiService.canManageDevices
                  ? () => _renameChannel(deviceId, ch)
                  : null,
              child: Row(
                children: [
                  Flexible(
                    child: Text(_channelName(deviceId, ch),
                        style: tt.bodyMedium
                            ?.copyWith(fontWeight: FontWeight.w600),
                        overflow: TextOverflow.ellipsis),
                  ),
                  if (ApiService.canManageDevices) ...[
                    const SizedBox(width: 6),
                    Icon(Icons.edit_outlined,
                        size: 13, color: cs.onSurfaceVariant.withOpacity(0.5)),
                  ],
                ],
              ),
            ),
          ),
          if (!allowed && ApiService.isChild)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: Icon(Icons.lock_outline_rounded,
                  size: 16, color: cs.onSurfaceVariant.withOpacity(0.4)),
            ),
          Switch.adaptive(
            value: isOn,
            onChanged: enabled
                ? (v) => _toggleChannel(deviceId, ch, v)
                : null,
            activeColor: color,
          ),
        ],
      ),
    );
  }
}
