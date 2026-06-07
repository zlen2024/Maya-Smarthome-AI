import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import '../services/api_service.dart';
import 'devices_tab.dart';
import 'chat_tab.dart';
import 'settings_tab.dart';

/// Child shell with 3-tab bottom navigation (Devices + Chat + Settings).
/// Children see only their permitted channels — no Children or Device tabs.
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

  final List<Widget> _tabs = const [
    DevicesTab(), // Child filter is applied inside DevicesTab
    ChatTab(),
    SettingsTab(),
  ];

  @override
  void initState() {
    super.initState();
    _connectWebSocket();
  }

  @override
  void dispose() {
    _reconnectTimer?.cancel();
    _channel?.sink.close();
    ApiService.activeChannel = null;
    super.dispose();
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
        onDestinationSelected: (i) => setState(() => _tabIndex = i),
        labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.power_settings_new_outlined),
            selectedIcon: Icon(Icons.power_settings_new_rounded),
            label: 'Devices',
          ),
          NavigationDestination(
            icon: Icon(Icons.chat_outlined),
            selectedIcon: Icon(Icons.chat_rounded),
            label: 'Chat',
          ),
          NavigationDestination(
            icon: Icon(Icons.settings_outlined),
            selectedIcon: Icon(Icons.settings_rounded),
            label: 'Settings',
          ),
        ],
      ),
    );
  }
}
