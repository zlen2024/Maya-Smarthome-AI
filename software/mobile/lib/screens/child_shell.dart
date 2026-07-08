import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import '../services/api_service.dart';
import 'devices_tab.dart';
import 'child_tasks_tab.dart';
import 'chat_tab.dart';
import 'settings_tab.dart';

/// Child shell with 4-tab bottom navigation (Devices + Tasks + Chat + Settings).
/// Children see only their permitted channels — no Children or Device tabs.
/// While this shell is alive it also reports the device's GPS position to the
/// server every few minutes so parents can see a last-known location.
class ChildShell extends StatefulWidget {
  const ChildShell({super.key});

  @override
  State<ChildShell> createState() => _ChildShellState();
}

class _ChildShellState extends State<ChildShell> {
  int _tabIndex = 0;
  WebSocketChannel? _channel;
  bool _wsConnected = false;
  Timer? _reconnectTimer;
  Timer? _locationTimer;
  int _unseenMentions = 0;
  StreamSubscription<void>? _mentionSub;
  static const int _chatTabIndex = 2;

  final List<Widget> _tabs = const [
    DevicesTab(), // Child filter is applied inside DevicesTab
    ChildTasksTab(),
    ChatTab(),
    SettingsTab(),
  ];

  @override
  void initState() {
    super.initState();
    _connectWebSocket();
    _startLocationReporting();
    _refreshMentions();
    _mentionSub = ApiService.mentionEvents.listen((_) => _refreshMentions());
  }

  @override
  void dispose() {
    _reconnectTimer?.cancel();
    _locationTimer?.cancel();
    _mentionSub?.cancel();
    _channel?.sink.close();
    ApiService.activeChannel = null;
    super.dispose();
  }

  // ── Unseen @-mention badge ─────────────────────────────────────
  Future<void> _refreshMentions() async {
    final houseId = ApiService.houseId;
    if (houseId == null) return;
    try {
      final data = await ApiService.getUnseenMentions(houseId);
      if (mounted) setState(() => _unseenMentions = (data['count'] ?? 0) as int);
    } catch (_) {}
  }

  Future<void> _markChatSeen() async {
    final houseId = ApiService.houseId;
    if (houseId == null) return;
    if (mounted) setState(() => _unseenMentions = 0);
    try {
      await ApiService.markMentionsSeen(houseId);
    } catch (_) {}
  }

  // ── Location Reporting (foreground only) ───────────────────────
  Future<void> _startLocationReporting() async {
    try {
      if (!await Geolocator.isLocationServiceEnabled()) return;
      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if (permission == LocationPermission.denied ||
          permission == LocationPermission.deniedForever) {
        return; // no permission — silently skip reporting
      }
      _reportLocation();
      _locationTimer =
          Timer.periodic(const Duration(minutes: 3), (_) => _reportLocation());
    } catch (_) {}
  }

  Future<void> _reportLocation() async {
    try {
      final pos = await Geolocator.getCurrentPosition(
        locationSettings:
            const LocationSettings(accuracy: LocationAccuracy.medium),
      ).timeout(const Duration(seconds: 20));
      await ApiService.reportLocation(pos.latitude, pos.longitude);
    } catch (_) {} // GPS or network hiccup — try again next tick
  }

  // ── WebSocket ──────────────────────────────────────────────────
  void _connectWebSocket() {
    _reconnectTimer?.cancel();
    try {
      final uri = Uri.parse('${ApiService.wsUrl}/ws/mobile');
      _channel = WebSocketChannel.connect(uri);
      ApiService.activeChannel = _channel;

      // Authenticate with token AND house_id
      _channel!.sink.add(jsonEncode({
        'token': ApiService.token,
        'house_id': ApiService.houseId,
      }));

      _channel!.stream.listen(
        (message) {
          final data = _parseJson(message);
          if (data == null) return;

          final type = data['type'];
          if (type == 'auth_ok') {
            if (mounted) setState(() => _wsConnected = true);
          } else if (type == 'device_update' || type == 'device_offline') {
            ApiService.emitBroadcast(data);
          } else if (type == 'chat_message') {
            ApiService.emitChat(data);
            if (_tabIndex == _chatTabIndex) {
              _markChatSeen();
            } else {
              _refreshMentions();
            }
          } else if (type == 'chat_cleared') {
            ApiService.emitChat(data);
          }
        },
        onDone: () {
          if (mounted) setState(() => _wsConnected = false);
          _scheduleReconnect();
        },
        onError: (_) {
          if (mounted) setState(() => _wsConnected = false);
          _scheduleReconnect();
        },
      );
    } catch (_) {
      _scheduleReconnect();
    }
  }

  void _scheduleReconnect() {
    _reconnectTimer?.cancel();
    if (ApiService.isLoggedIn) {
      _reconnectTimer = Timer(const Duration(seconds: 5), _connectWebSocket);
    }
  }

  Map<String, dynamic>? _parseJson(dynamic raw) {
    try {
      return jsonDecode(raw as String) as Map<String, dynamic>;
    } catch (_) {
      return null;
    }
  }

  // ── Build ──────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Maya Smart Home'),
        centerTitle: false,
        titleTextStyle: Theme.of(context).textTheme.titleLarge?.copyWith(
              fontWeight: FontWeight.w800,
            ),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 9,
                  height: 9,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: _wsConnected ? Colors.green : cs.error,
                    boxShadow: [
                      BoxShadow(
                        color: (_wsConnected ? Colors.green : cs.error)
                            .withOpacity(0.5),
                        blurRadius: 6,
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 6),
                Text(
                  _wsConnected ? 'Live' : 'Offline',
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                        color: cs.onSurfaceVariant,
                      ),
                ),
              ],
            ),
          ),
        ],
      ),
      body: IndexedStack(
        index: _tabIndex,
        children: _tabs,
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tabIndex,
        onDestinationSelected: (i) {
          setState(() => _tabIndex = i);
          if (i == _chatTabIndex) _markChatSeen();
        },
        labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
        destinations: [
          const NavigationDestination(
            icon: Icon(Icons.power_settings_new_outlined),
            selectedIcon: Icon(Icons.power_settings_new_rounded),
            label: 'Devices',
          ),
          const NavigationDestination(
            icon: Icon(Icons.task_alt_outlined),
            selectedIcon: Icon(Icons.task_alt_rounded),
            label: 'Tasks',
          ),
          NavigationDestination(
            icon: Badge(
              isLabelVisible: _unseenMentions > 0,
              label: Text('$_unseenMentions'),
              child: const Icon(Icons.chat_outlined),
            ),
            selectedIcon: const Icon(Icons.chat_rounded),
            label: 'Chat',
          ),
          const NavigationDestination(
            icon: Icon(Icons.settings_outlined),
            selectedIcon: Icon(Icons.settings_rounded),
            label: 'Settings',
          ),
        ],
      ),
    );
  }
}
