import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import '../services/api_service.dart';
import 'devices_tab.dart';
import 'children_tab.dart';
import 'device_management_tab.dart';
import 'settings_tab.dart';

/// Parent shell with 4-tab bottom navigation and persistent WebSocket.
class ParentShell extends StatefulWidget {
  const ParentShell({super.key});

  @override
  State<ParentShell> createState() => _ParentShellState();
}

class _ParentShellState extends State<ParentShell> {
  int _tabIndex = 0;
  WebSocketChannel? _channel;
  bool _wsConnected = false;
  Timer? _reconnectTimer;

  // Keep tab pages alive across switches
  final List<Widget> _tabs = const [
    DevicesTab(),
    ChildrenTab(),
    DeviceManagementTab(),
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
    super.dispose();
  }

  // ── WebSocket ──────────────────────────────────────────────────
  void _connectWebSocket() {
    _reconnectTimer?.cancel();
    try {
      final uri = Uri.parse('${ApiService.wsUrl}/ws/mobile');
      _channel = WebSocketChannel.connect(uri);

      // Authenticate
      _channel!.sink.add(jsonEncode({'token': ApiService.token}));

      _channel!.stream.listen(
        (message) {
          final data = _parseJson(message);
          if (data == null) return;

          final type = data['type'];
          if (type == 'auth_ok') {
            if (mounted) setState(() => _wsConnected = true);
          } else if (type == 'device_update' || type == 'device_offline') {
            ApiService.emitBroadcast(data);
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
          // WebSocket status dot
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
            icon: Icon(Icons.people_outline_rounded),
            selectedIcon: Icon(Icons.people_rounded),
            label: 'Children',
          ),
          NavigationDestination(
            icon: Icon(Icons.settings_remote_outlined),
            selectedIcon: Icon(Icons.settings_remote_rounded),
            label: 'Device',
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
