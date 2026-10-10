import 'dart:async';
import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../widgets/capability_control.dart';

/// Main device dashboard, rendered from each device's own descriptor.
///
/// This is protocol 2 step 2 (PROTOCOL.md §10): the UI is chosen by capability
/// `kind`, never by device model, so new hardware appears here without this file
/// changing. Every device has a descriptor — the server synthesises one for
/// firmware that declares nothing — so there is no second code path for the
/// three-channel extensions that shipped first.
///
/// What a child may change comes from `may_write` on each capability (§5.10);
/// reading is house-wide, so a locked control is shown rather than hidden.
class DevicesTab extends StatefulWidget {
  const DevicesTab({super.key});

  @override
  State<DevicesTab> createState() => _DevicesTabState();
}

class _DevicesTabState extends State<DevicesTab>
    with AutomaticKeepAliveClientMixin {
  List<dynamic> _devices = [];

  /// device_id -> the descriptor payload: capabilities, state, proto, model.
  final Map<String, Map<String, dynamic>> _caps = {};

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
    _broadcastSub = ApiService.broadcasts.listen(_handleBroadcast);
    _pollTimer = Timer.periodic(const Duration(seconds: 10), (_) => _fetchAll());
  }

  @override
  void dispose() {
    _broadcastSub?.cancel();
    _pollTimer?.cancel();
    super.dispose();
  }

  // ── Data ───────────────────────────────────────────────────────
  Future<void> _fetchAll() async {
    try {
      final devices = await ApiService.getDevices();
      // One descriptor read per device. A household has a handful, and each
      // answer carries the capabilities, their current values and — for a child
      // — what they are allowed to change.
      final caps = <String, Map<String, dynamic>>{};
      for (final d in devices) {
        final id = d['device_id'] as String?;
        if (id == null) continue;
        try {
          caps[id] = await ApiService.getCapabilities(id);
        } catch (_) {
          // A device that cannot be read still belongs on the list; it just
          // shows no controls.
        }
      }
      if (!mounted) return;
      setState(() {
        _devices = devices;
        _caps
          ..clear()
          ..addAll(caps);
        _loading = false;
        _error = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = e.toString().replaceFirst('Exception: ', '');
      });
    }
  }

  void _handleBroadcast(Map<String, dynamic> data) {
    final type = data['type'];
    final deviceId = data['device_id'] as String?;
    if (deviceId == null) return;

    setState(() {
      final idx = _devices.indexWhere((d) => d['device_id'] == deviceId);
      if (idx != -1) {
        if (type == 'device_update') _devices[idx]['online'] = true;
        if (type == 'device_offline') _devices[idx]['online'] = false;
      }
      if (type != 'device_update') return;

      final state = _stateOf(deviceId);
      // A v2 device sends `state`; a protocol-1 one sends bare channel keys.
      // Both are merged into the same map, because the descriptor is the only
      // shape this screen knows.
      final reported = data['state'];
      if (reported is Map) {
        reported.forEach((k, v) => state[k.toString()] = v);
      }
      for (final key in const ['ch1', 'ch2', 'ch3']) {
        if (data[key] != null) state[key] = data[key];
      }
    });
  }

  Map<String, dynamic> _stateOf(String deviceId) {
    final entry = _caps.putIfAbsent(deviceId, () => {'capabilities': [], 'state': {}});
    final state = entry['state'];
    if (state is Map<String, dynamic>) return state;
    final fresh = <String, dynamic>{};
    if (state is Map) state.forEach((k, v) => fresh[k.toString()] = v);
    entry['state'] = fresh;
    return fresh;
  }

  List<Map<String, dynamic>> _capsOf(String deviceId) {
    final raw = _caps[deviceId]?['capabilities'];
    if (raw is! List) return const [];
    return raw
        .whereType<Map>()
        .map((m) => Map<String, dynamic>.from(m))
        .toList();
  }

  // ── Actions ────────────────────────────────────────────────────
  /// [confirmed] is only true for a capability declared `confirm: true`, and
  /// only reaches here after `CapabilityControl` has actually asked — the flag
  /// is evidence of a human's yes (§5.4), not a formality to tick.
  Future<void> _set(String deviceId, String key, dynamic value,
      {bool confirmed = false}) async {
    final state = _stateOf(deviceId);
    final previous = state[key];
    setState(() => state[key] = value);
    try {
      final result = await ApiService.setCapability(deviceId, {key: value},
          confirmed: confirmed);
      final status = result['status'];
      if (status != 'ok') {
        setState(() => state[key] = previous);
        _snack(_explain(status, result));
        return;
      }
      // Believe the device's own echo over what we asked for (§6.2).
      final echoed = result['state'];
      if (echoed is Map && echoed.isNotEmpty) {
        setState(() => echoed.forEach((k, v) => state[k.toString()] = v));
      }
    } catch (e) {
      setState(() => state[key] = previous);
      _snack(e.toString().replaceFirst('Exception: ', ''));
    }
  }

  /// Ack statuses are protocol words (§9); say them in a person's words.
  String _explain(dynamic status, Map<String, dynamic> result) {
    final failed = result['failed'];
    final detail = result['detail'];
    switch (status) {
      case 'not_connected':
        return 'That device is offline right now.';
      case 'timeout':
        return "The device didn't respond — try again.";
      case 'blocked':
        return 'That device is blocked.';
      case 'bad_value':
        return detail?.toString() ?? 'The device refused that value.';
      case 'not_permitted':
        return detail?.toString() ?? 'Not allowed.';
      case 'busy':
        return failed == null
            ? 'The device is busy — try again.'
            : 'The device was busy and did not change $failed.';
      case 'unknown_capability':
        return 'This device no longer has that control.';
      default:
        return detail?.toString() ?? 'That did not work ($status).';
    }
  }

  Future<void> _rename(String deviceId, Map<String, dynamic> cap) async {
    final key = cap['key'] as String;
    final ctrl = TextEditingController(text: (cap['label'] ?? key) as String);
    final result = await showDialog<_RenameResult>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Rename'),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          maxLength: 40,
          decoration: const InputDecoration(
            labelText: 'Name',
            helperText: "Clearing it restores the device's own name",
          ),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
          // §5.11: clearing *is* the reset — there is no third state.
          TextButton(
              onPressed: () => Navigator.pop(ctx, const _RenameResult(null)),
              child: const Text('Reset')),
          FilledButton(
              onPressed: () =>
                  Navigator.pop(ctx, _RenameResult(ctrl.text.trim())),
              child: const Text('Save')),
        ],
      ),
    );
    if (result == null) return;
    try {
      final label = await ApiService.renameCapability(deviceId, key, result.label);
      setState(() => cap['label'] = label);
      // The list held by _caps is a copy, so write the new name back into it.
      final list = _caps[deviceId]?['capabilities'];
      if (list is List) {
        for (final item in list) {
          if (item is Map && item['key'] == key) item['label'] = label;
        }
      }
    } catch (e) {
      _snack(e.toString().replaceFirst('Exception: ', ''));
    }
  }

  Future<void> _removeDevice(String deviceId, String name) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Remove device?'),
        content: Text(
            '$name will be wiped back to setup mode and removed from this house.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          FilledButton(
            style: FilledButton.styleFrom(
                backgroundColor: Theme.of(ctx).colorScheme.error),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Remove'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await ApiService.deleteDevice(deviceId);
      await _fetchAll();
      _snack('$name removed');
    } catch (e) {
      _snack(e.toString().replaceFirst('Exception: ', ''));
    }
  }

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(message),
      behavior: SnackBarBehavior.floating,
    ));
  }

  // ── Build ──────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    super.build(context);
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;

    if (_loading) return const Center(child: CircularProgressIndicator());

    if (_error != null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline_rounded, size: 48, color: cs.error),
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
            Icon(Icons.sensors_off_rounded,
                size: 56, color: cs.onSurfaceVariant.withOpacity(0.35)),
            const SizedBox(height: 12),
            Text('No devices connected',
                style: tt.titleMedium?.copyWith(color: cs.onSurfaceVariant)),
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

  /// Colours cycle so neighbouring controls stay distinguishable. They are
  /// decoration only — nothing reads meaning into the order, because the
  /// descriptor decides what is in the list.
  static const _accents = [
    Color(0xFFEF4444),
    Color(0xFF10B981),
    Color(0xFF3B82F6),
    Color(0xFFF59E0B),
    Color(0xFF8B5CF6),
  ];

  Widget _deviceCard(dynamic device, ColorScheme cs, TextTheme tt) {
    final deviceId = device['device_id'] as String;
    final name = device['name'] ?? deviceId;
    final online = device['online'] == true;
    final all = _capsOf(deviceId);
    final state = _stateOf(deviceId);

    // §5.3: reserved keys are device chrome, not controls — except
    // `_report_every`, which is a setting and belongs with the rest.
    final chrome = all
        .where((c) => (c['key'] as String).startsWith('_') &&
            c['key'] != '_report_every')
        .toList();
    final controls = all
        .where((c) => !(c['key'] as String).startsWith('_') ||
            c['key'] == '_report_every')
        .toList();

    return Card(
      margin: const EdgeInsets.only(bottom: 14),
      color: cs.surfaceContainerLow,
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
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
                _statusPill(online, cs, tt),
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
            CapabilityChrome(capabilities: chrome, state: state),
            const SizedBox(height: 12),
            if (controls.isEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Text(
                  online
                      ? 'This device reports no controls.'
                      : "Waiting for this device to say what it can do.",
                  style: tt.bodySmall?.copyWith(color: cs.onSurfaceVariant),
                ),
              )
            else
              for (int i = 0; i < controls.length; i++)
                _control(deviceId, controls[i], _accents[i % _accents.length],
                    online),
          ],
        ),
      ),
    );
  }

  Widget _control(String deviceId, Map<String, dynamic> cap, Color accent,
      bool online) {
    final key = cap['key'] as String;
    final access = (cap['access'] ?? 'rw') as String;
    final readOnly = access == 'r';
    // A child's grant decides writability; for an adult, `may_write` is absent
    // and the capability's own access is the only limit (§5.10).
    final granted = cap.containsKey('may_write') ? cap['may_write'] == true : true;
    return CapabilityControl(
      key: ValueKey('$deviceId/$key'),
      capability: cap,
      value: _stateOf(deviceId)[key],
      enabled: online && !readOnly && granted,
      accent: accent,
      onSet: (value) =>
          _set(deviceId, key, value, confirmed: cap['confirm'] == true),
      onRename: ApiService.canManageDevices ? () => _rename(deviceId, cap) : null,
    );
  }

  Widget _statusPill(bool online, ColorScheme cs, TextTheme tt) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
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
    );
  }
}

/// Distinguishes "cleared the name" from "cancelled the dialog", which `null`
/// alone cannot.
class _RenameResult {
  const _RenameResult(this.label);
  final String? label;
}
