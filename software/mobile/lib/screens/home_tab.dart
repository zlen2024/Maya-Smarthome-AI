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

  /// device_id -> the descriptor payload (capabilities + state), the same read the
  /// Devices tab makes. It lets this screen tell a 3-channel socket from anything else.
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

  /// One refresh at a time: a slow network must not let every 10 s tick start another chain
  /// of requests, nor let an old chain finish late and overwrite newer state.
  bool _fetching = false;

  Future<void> _fetchAll() async {
    if (_fetching) return;
    _fetching = true;
    try {
      await _fetchAllOnce();
    } finally {
      _fetching = false;
    }
  }

  Future<void> _fetchAllOnce() async {
    try {
      final devices = await ApiService.getDevices();
      final caps = <String, Map<String, dynamic>>{};
      for (final d in devices) {
        final id = d['device_id'] as String?;
        if (id == null) continue;
        try {
          caps[id] = await ApiService.getCapabilities(id)
              .timeout(const Duration(seconds: 8));
        } catch (_) {
          // One failed read must not turn a scale back into three "Channel" switches
          // for ten seconds: keep what was known. A device never read before is drawn
          // as the 3-channel socket it used to be.
          final before = _caps[id];
          if (before != null) caps[id] = before;
        }
      }
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
          _caps
            ..clear()
            ..addAll(caps);
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
        // A protocol-2 board sends only the channels that changed; a protocol-1 board sends
        // all three. Copy only what is present, or an unchanged channel is blanked.
        for (final k in const ['ch1', 'ch2', 'ch3']) {
          if (data.containsKey(k)) _devices[idx][k] = data[k];
        }
        _devices[idx]['online'] = true;
        // A protocol-2 device sends its readings as `state`; keep them for the card.
        final reported = data['state'];
        if (reported is Map) {
          final entry = _caps.putIfAbsent(
              deviceId as String, () => {'capabilities': [], 'state': {}});
          final st = entry['state'] is Map
              ? Map<String, dynamic>.from(entry['state'] as Map)
              : <String, dynamic>{};
          reported.forEach((k, v) => st[k.toString()] = v);
          entry['state'] = st;
        }
      } else if (data['type'] == 'device_offline') {
        _devices[idx]['online'] = false;
      }
    });
  }

  // ── Which drawing a device gets ────────────────────────────────────────
  /// The original 3-channel board, or anything that names ch1..ch3, is drawn as three
  /// switches. A device that says it is something else (a scale, a sensor) is drawn from
  /// what it reports, because three "Channel" switches on it are meaningless.
  bool _isSocketBoard(String deviceId) {
    final raw = _caps[deviceId]?['capabilities'];
    if (raw is! List || raw.isEmpty) return true; // not known yet: keep the old drawing
    return raw
        .whereType<Map>()
        .any((c) => const ['ch1', 'ch2', 'ch3'].contains(c['key']));
  }

  String _formatReading(Map<String, dynamic> cap, dynamic v) {
    if (v == null) return '—';
    final kind = cap['kind'];
    if (kind == 'switch') return (v == true || v == 'on') ? 'On' : 'Off';
    if (v is num) {
      final n = v == v.roundToDouble() ? v.toInt().toString() : v.toStringAsFixed(1);
      final unit = cap['unit'];
      return unit is String && unit.isNotEmpty ? '$n $unit' : n;
    }
    return v.toString();
  }

  /// One line per declared capability (reserved `_` keys are device chrome, skipped).
  List<Widget> _readingRows(String deviceId) {
    final raw = _caps[deviceId]?['capabilities'];
    final state = _caps[deviceId]?['state'];
    final st = state is Map ? state : const {};
    final caps = (raw is List ? raw : const [])
        .whereType<Map>()
        .map((m) => Map<String, dynamic>.from(m))
        // Reserved `_` keys are chrome; a button has no reading to show.
        .where((c) => !'${c['key']}'.startsWith('_') && c['kind'] != 'button')
        .toList();
    final rows = <Widget>[];
    var anyWritable = false;
    for (final c in caps) {
      if ((c['access'] ?? 'rw') != 'r') anyWritable = true;
      rows.add(Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(
          children: [
            Expanded(
              child: Text((c['label'] ?? c['key']).toString(),
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                      fontSize: 14.5,
                      fontWeight: FontWeight.w600,
                      color: context.pal.ink)),
            ),
            Text(_formatReading(c, st[c['key']]),
                style: TextStyle(
                    fontSize: 14.5,
                    fontWeight: FontWeight.w700,
                    color: context.pal.ink)),
          ],
        ),
      ));
    }
    if (rows.isEmpty) {
      rows.add(Text('Waiting for this device to report.',
          style: TextStyle(fontSize: 12.5, color: context.pal.muted)));
    } else if (anyWritable) {
      rows.add(Padding(
        padding: const EdgeInsets.only(top: 6),
        child: Text('Controls are in the Devices tab.',
            style: TextStyle(fontSize: 12, color: context.pal.muted)),
      ));
    }
    return rows;
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
    final accent = context.pal;

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



  Widget _statusRow(Palette accent) {
    final total = _devices.length;
    final online = _onlineCount;
    return Row(
      children: [
        GlassPill(
          dot: online > 0 ? context.pal.ink : context.pal.faint,
          child: Text('$online of $total online'),
        ),
        const SizedBox(width: 10),
        GlassPill(child: Text(ApiService.isChild ? 'Child mode' : 'Parent')),
      ],
    );
  }

  Widget _allOffCard(Palette accent) {
    return GlassSurface(
      onTap: _allOff,
      child: Row(
        children: [
          Container(
            width: 46,
            height: 46,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: context.pal.ink,
              borderRadius: BorderRadius.circular(14),
            ),
            child: Icon(Icons.power_settings_new_rounded, color: context.pal.onInk),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('All off',
                    style: TextStyle(
                        fontSize: 16, fontWeight: FontWeight.w700, color: context.pal.ink)),
                const SizedBox(height: 2),
                Text('Turn everything off',
                    style: TextStyle(fontSize: 12.5, color: context.pal.muted)),
              ],
            ),
          ),
          Icon(Icons.chevron_right_rounded, color: context.pal.faint),
        ],
      ),
    );
  }

  // ── Device (room) card ─────────────────────────────────────────────────
  Widget _deviceCard(dynamic device, Palette accent) {
    final deviceId = device['device_id'] as String;
    final name = device['name'] ?? deviceId;
    final online = device['online'] == true;
    final onCount = [1, 2, 3].where((c) => device['ch$c'] == 'on').length;

    return GlassSurface(
      glow: onCount > 0 && online ? context.pal.ink : null,
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
                  color: onCount > 0 && online ? context.pal.ink : context.pal.sunken,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(Icons.bolt_rounded,
                    color: onCount > 0 && online
                        ? context.pal.onInk
                        : online ? context.pal.ink : context.pal.faint,
                    size: 22),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(name,
                        style: TextStyle(
                            fontSize: 16, fontWeight: FontWeight.w700, color: context.pal.ink)),
                    Text(deviceId,
                        style: TextStyle(
                            fontSize: 11,
                            color: context.pal.faint,
                            fontFamily: 'monospace')),
                  ],
                ),
              ),
              GlassPill(
                dot: online ? context.pal.ok : context.pal.danger,
                child: Text(online ? 'Online' : 'Offline'),
              ),
              // ⋮ menu — delete device (parent/master only)
              if (ApiService.canManageDevices)
                PopupMenuButton<String>(
                  icon: Icon(Icons.more_vert_rounded,
                      size: 20, color: context.pal.faint),
                  color: context.pal.surface,
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
                              size: 18, color: context.pal.danger),
                          const SizedBox(width: 8),
                          Text('Remove device',
                              style: TextStyle(color: context.pal.danger)),
                        ],
                      ),
                    ),
                  ],
                ),
            ],
          ),
          const SizedBox(height: 14),
          if (_isSocketBoard(deviceId))
            for (int ch = 1; ch <= 3; ch++) _channelRow(device, ch, accent, online)
          else
            ..._readingRows(deviceId),
        ],
      ),
    );
  }

  Widget _channelRow(dynamic device, int ch, Palette accent, bool online) {
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
              color: isOn ? context.pal.ink : context.pal.faint,
              boxShadow: isOn
                  ? [BoxShadow(color: context.pal.ink.withOpacity(0.6), blurRadius: 8)]
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
                        color: enabled ? context.pal.ink : context.pal.faint,
                      ),
                    ),
                  ),
                  if (ApiService.canManageDevices) ...[
                    const SizedBox(width: 6),
                    Icon(Icons.edit_outlined,
                        size: 12, color: context.pal.faint),
                  ],
                ],
              ),
            ),
          ),
          if (!allowed && ApiService.isChild)
            Padding(
              padding: const EdgeInsets.only(right: 6),
              child: Icon(Icons.lock_outline_rounded,
                  size: 15, color: context.pal.faint),
            ),
          Switch.adaptive(
            value: isOn,
            activeColor: context.pal.onInk,
            activeTrackColor: context.pal.ink,
            onChanged: enabled ? (v) => _toggleChannel(deviceId, ch, v) : null,
          ),
        ],
      ),
    );
  }

  Widget _askMaya(Palette accent) {
    return GlassSurface(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      radius: 30,
      onTap: widget.onAskMaya,
      child: Row(
        children: [
          Icon(Icons.auto_awesome_rounded, color: context.pal.ink, size: 20),
          const SizedBox(width: 12),
          Text('Ask Maya…',
              style: TextStyle(fontSize: 15, color: context.pal.muted)),
        ],
      ),
    );
  }

  Widget _errorCard() => GlassSurface(
        child: Row(
          children: [
            Icon(Icons.error_outline_rounded, color: context.pal.danger),
            const SizedBox(width: 12),
            Expanded(child: Text(_error!, style: TextStyle(color: context.pal.muted))),
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
            Icon(Icons.sensors_off_rounded, size: 44, color: context.pal.faint),
            const SizedBox(height: 12),
            Text('No devices yet',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: context.pal.ink)),
            const SizedBox(height: 4),
            Text(
              ApiService.isChild
                  ? 'Ask your parent to add devices.'
                  : 'Add one from the Device tab.',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 13, color: context.pal.muted),
            ),
          ],
        ),
      );
}
