import 'dart:async';
import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../theme/accents.dart';
import '../widgets/glass.dart';

/// Glass home dashboard: greeting, live device status, quick "all off", and a
/// glass card per device (room) with its channel toggles. Uses only existing
/// device/relay APIs — no new backend logic.
class HomeTab extends StatefulWidget {
  /// Jump to the Chat tab (wired from the shell) when the user taps "Ask Maya".
  final VoidCallback? onAskMaya;

  /// House switching callbacks wired from the parent shell.
  final Future<void> Function(int?)? onHouseSelected;
  final VoidCallback? onCreateHouse;
  final VoidCallback? onJoinHouse;

  const HomeTab({
    super.key,
    this.onAskMaya,
    this.onHouseSelected,
    this.onCreateHouse,
    this.onJoinHouse,
  });

  @override
  State<HomeTab> createState() => _HomeTabState();
}

class _HomeTabState extends State<HomeTab> with AutomaticKeepAliveClientMixin {
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
    _broadcastSub = ApiService.broadcasts.listen(_handleBroadcast);
    _pollTimer = Timer.periodic(const Duration(seconds: 10), (_) => _fetchAll());
  }

  @override
  void dispose() {
    _broadcastSub?.cancel();
    _pollTimer?.cancel();
    super.dispose();
  }

  Future<void> _fetchAll() async {
    try {
      final devices = await ApiService.getDevices();
      List<dynamic> relays = [];
      List<dynamic> perms = [];
      try {
        relays = await ApiService.getRelays();
      } catch (_) {}
      try {
        perms = ApiService.isChild
            ? await ApiService.getPermissions(childId: ApiService.accId)
            : await ApiService.getPermissions();
      } catch (_) {}
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

  void _handleBroadcast(Map<String, dynamic> data) {
    final deviceId = data['device_id'];
    if (deviceId == null) return;
    setState(() {
      final idx = _devices.indexWhere((d) => d['device_id'] == deviceId);
      if (idx == -1) return;
      if (data['type'] == 'device_update') {
        _devices[idx]['ch1'] = data['ch1'];
        _devices[idx]['ch2'] = data['ch2'];
        _devices[idx]['ch3'] = data['ch3'];
        _devices[idx]['online'] = true;
      } else if (data['type'] == 'device_offline') {
        _devices[idx]['online'] = false;
      }
    });
  }

  // ── Channel helpers (mirror devices_tab; presentation state only) ──────
  Map<String, dynamic>? _relayFor(String deviceId, int ch) {
    for (final r in _relays) {
      if (r['device_id'] == deviceId && r['channel_number'] == ch) {
        return Map<String, dynamic>.from(r as Map);
      }
    }
    return null;
  }

  String _channelName(String deviceId, int ch) {
    final name = _relayFor(deviceId, ch)?['name'] as String?;
    return (name == null || name.isEmpty) ? 'Channel $ch' : name;
  }

  bool _isChannelAllowed(String deviceId, int ch) {
    if (!ApiService.isChild) return true;
    final relay = _relayFor(deviceId, ch);
    if (relay == null) return false;
    final perm = _permissions.firstWhere(
      (p) => p['relay_id'] == relay['relay_id'],
      orElse: () => null,
    );
    return perm != null && perm['is_allowed'] == true;
  }

  Future<void> _toggleChannel(String deviceId, int ch, bool on) async {
    setState(() {
      final idx = _devices.indexWhere((d) => d['device_id'] == deviceId);
      if (idx != -1) _devices[idx]['ch$ch'] = on ? 'on' : 'off';
    });
    try {
      await ApiService.sendCommand(deviceId, on ? 'output_on' : 'output_off', channel: ch);
    } catch (e) {
      setState(() {
        final idx = _devices.indexWhere((d) => d['device_id'] == deviceId);
        if (idx != -1) _devices[idx]['ch$ch'] = on ? 'off' : 'on';
      });
      _snack(e.toString().replaceFirst('Exception: ', ''));
    }
  }

  // ── Rename channel (ported from devices_tab) ──────────────────────────
  Future<void> _renameChannel(String deviceId, int ch) async {
    final relay = _relayFor(deviceId, ch);
    if (relay == null) return;
    final ctrl = TextEditingController(text: _channelName(deviceId, ch));
    final newName = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Rename channel $ch'),
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
      _snack(e.toString().replaceFirst('Exception: ', ''));
    }
  }

  // ── Remove device (ported from devices_tab) ───────────────────────────
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
      _snack('Device removed — it has been reset to setup mode');
    } catch (e) {
      _snack(e.toString().replaceFirst('Exception: ', ''));
    }
  }

  /// "All off" scene = turn off every on channel across every online device.
  /// Real bulk commands over the existing API — no scenes backend invented.
  Future<void> _allOff() async {
    final targets = <MapEntry<String, int>>[];
    for (final d in _devices) {
      if (d['online'] != true) continue;
      final id = d['device_id'] as String;
      for (var ch = 1; ch <= 3; ch++) {
        if (d['ch$ch'] == 'on') targets.add(MapEntry(id, ch));
      }
    }
    if (targets.isEmpty) {
      _snack('Everything is already off');
      return;
    }
    setState(() {
      for (final t in targets) {
        final idx = _devices.indexWhere((d) => d['device_id'] == t.key);
        if (idx != -1) _devices[idx]['ch${t.value}'] = 'off';
      }
    });
    for (final t in targets) {
      try {
        await ApiService.sendCommand(t.key, 'output_off', channel: t.value);
      } catch (_) {}
    }
  }

  void _snack(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), behavior: SnackBarBehavior.floating),
    );
  }

  int get _onlineCount => _devices.where((d) => d['online'] == true).length;

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final accent = ThemeController.instance.accent;

    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }

    return SafeArea(
      bottom: false,
      child: RefreshIndicator(
      onRefresh: _fetchAll,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
        children: [
          _statusRow(accent),
          const SizedBox(height: 20),
          _allOffCard(accent),
          const SizedBox(height: 16),
          if (_error != null)
            _errorCard()
          else if (_devices.isEmpty)
            _emptyCard()
          else
            ..._devices.map((d) => Padding(
                  padding: const EdgeInsets.only(bottom: 14),
                  child: _deviceCard(d, accent),
                )),
          const SizedBox(height: 8),
          _askMaya(accent),
        ],
      ),
      ),
    );
  }



  Widget _statusRow(AccentPreset accent) {
    final total = _devices.length;
    final online = _onlineCount;
    return Row(
      children: [
        GlassPill(
          dot: online > 0 ? accent.accent : Colors.grey,
          child: Text('$online of $total online'),
        ),
        const SizedBox(width: 10),
        GlassPill(child: Text(ApiService.isChild ? 'Child mode' : 'Parent')),
      ],
    );
  }

  Widget _allOffCard(AccentPreset accent) {
    return GlassSurface(
      onTap: _allOff,
      child: Row(
        children: [
          Container(
            width: 46,
            height: 46,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: accent.accent.withOpacity(0.18),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Icon(Icons.power_settings_new_rounded, color: accent.accent),
          ),
          const SizedBox(width: 14),
          const Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('All off',
                    style: TextStyle(
                        fontSize: 16, fontWeight: FontWeight.w700, color: Colors.white)),
                SizedBox(height: 2),
                Text('Turn everything off',
                    style: TextStyle(fontSize: 12.5, color: Colors.white54)),
              ],
            ),
          ),
          Icon(Icons.chevron_right_rounded, color: Colors.white.withOpacity(0.4)),
        ],
      ),
    );
  }

  // ── Device (room) card ─────────────────────────────────────────────────
  Widget _deviceCard(dynamic device, AccentPreset accent) {
    final deviceId = device['device_id'] as String;
    final name = device['name'] ?? deviceId;
    final online = device['online'] == true;
    final onCount = [1, 2, 3].where((c) => device['ch$c'] == 'on').length;

    return GlassSurface(
      glow: onCount > 0 && online ? accent.accent : null,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 40,
                height: 40,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: Colors.white.withOpacity(0.08),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(Icons.bolt_rounded,
                    color: online ? accent.accent : Colors.white38, size: 22),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(name,
                        style: const TextStyle(
                            fontSize: 16, fontWeight: FontWeight.w700, color: Colors.white)),
                    Text('$deviceId',
                        style: TextStyle(
                            fontSize: 11,
                            color: Colors.white.withOpacity(0.35),
                            fontFamily: 'monospace')),
                  ],
                ),
              ),
              GlassPill(
                dot: online ? const Color(0xFF34D399) : Colors.redAccent,
                child: Text(online ? 'Online' : 'Offline'),
              ),
              // ⋮ menu — delete device (parent/master only)
              if (ApiService.canManageDevices)
                PopupMenuButton<String>(
                  icon: Icon(Icons.more_vert_rounded,
                      size: 20, color: Colors.white.withOpacity(0.4)),
                  color: const Color(0xFF1A1F35),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12)),
                  onSelected: (v) {
                    if (v == 'remove') _removeDevice(deviceId, name);
                  },
                  itemBuilder: (ctx) => [
                    PopupMenuItem(
                      value: 'remove',
                      child: Row(
                        children: [
                          Icon(Icons.delete_outline_rounded,
                              size: 18, color: Colors.redAccent),
                          const SizedBox(width: 8),
                          const Text('Remove device',
                              style: TextStyle(color: Colors.redAccent)),
                        ],
                      ),
                    ),
                  ],
                ),
            ],
          ),
          const SizedBox(height: 14),
          for (int ch = 1; ch <= 3; ch++) _channelRow(device, ch, accent, online),
        ],
      ),
    );
  }

  Widget _channelRow(dynamic device, int ch, AccentPreset accent, bool online) {
    final deviceId = device['device_id'] as String;
    final isOn = device['ch$ch'] == 'on';
    final allowed = _isChannelAllowed(deviceId, ch);
    final enabled = online && allowed;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          Container(
            width: 9,
            height: 9,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: isOn ? accent.accent : Colors.white.withOpacity(0.2),
              boxShadow: isOn
                  ? [BoxShadow(color: accent.accent.withOpacity(0.6), blurRadius: 8)]
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
                    child: Text(
                      _channelName(deviceId, ch),
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 14.5,
                        fontWeight: FontWeight.w600,
                        color: enabled ? Colors.white : Colors.white38,
                      ),
                    ),
                  ),
                  if (ApiService.canManageDevices) ...[
                    const SizedBox(width: 6),
                    Icon(Icons.edit_outlined,
                        size: 12, color: Colors.white.withOpacity(0.3)),
                  ],
                ],
              ),
            ),
          ),
          if (!allowed && ApiService.isChild)
            Padding(
              padding: const EdgeInsets.only(right: 6),
              child: Icon(Icons.lock_outline_rounded,
                  size: 15, color: Colors.white.withOpacity(0.4)),
            ),
          Switch.adaptive(
            value: isOn,
            activeColor: accent.onAccent,
            activeTrackColor: accent.accent,
            onChanged: enabled ? (v) => _toggleChannel(deviceId, ch, v) : null,
          ),
        ],
      ),
    );
  }

  Widget _askMaya(AccentPreset accent) {
    return GlassSurface(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      radius: 30,
      onTap: widget.onAskMaya,
      child: Row(
        children: [
          Icon(Icons.auto_awesome_rounded, color: accent.accent, size: 20),
          const SizedBox(width: 12),
          Text('Ask Maya…',
              style: TextStyle(fontSize: 15, color: Colors.white.withOpacity(0.55))),
        ],
      ),
    );
  }

  Widget _errorCard() => GlassSurface(
        child: Row(
          children: [
            const Icon(Icons.error_outline_rounded, color: Colors.redAccent),
            const SizedBox(width: 12),
            Expanded(child: Text(_error!, style: const TextStyle(color: Colors.white70))),
            TextButton(
              onPressed: () {
                setState(() => _loading = true);
                _fetchAll();
              },
              child: const Text('Retry'),
            ),
          ],
        ),
      );

  Widget _emptyCard() => GlassSurface(
        padding: const EdgeInsets.symmetric(vertical: 28, horizontal: 18),
        child: Column(
          children: [
            Icon(Icons.sensors_off_rounded, size: 44, color: Colors.white.withOpacity(0.3)),
            const SizedBox(height: 12),
            const Text('No devices yet',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: Colors.white)),
            const SizedBox(height: 4),
            Text(
              ApiService.isChild
                  ? 'Ask your parent to add devices.'
                  : 'Add one from the Device tab.',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 13, color: Colors.white.withOpacity(0.5)),
            ),
          ],
        ),
      );
}
