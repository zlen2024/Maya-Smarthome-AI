import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import '../services/api_service.dart';
import 'devices_tab.dart';
import 'children_tab.dart';
import 'chat_tab.dart';
import 'device_management_tab.dart';
import 'settings_tab.dart';

/// Parent shell with 5-tab bottom navigation and persistent WebSocket.
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
    ChatTab(),
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

  void _reconnectForHouse() {
    _channel?.sink.close();
    ApiService.activeChannel = null;
    _wsConnected = false;
    _connectWebSocket();
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

  // ── House Switching ────────────────────────────────────────────
  Future<void> _onHouseSelected(int? value) async {
    if (value == null) return;

    if (value == -1) {
      // "Create House"
      _showCreateHouseDialog();
      return;
    }
    if (value == -2) {
      // "Join House"
      _showJoinHouseDialog();
      return;
    }

    // Switch to an existing house
    if (value == ApiService.houseId) return;

    try {
      await ApiService.switchHouse(value);
      _reconnectForHouse();
      if (mounted) setState(() {});
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content:
              Text(e.toString().replaceFirst('Exception: ', '')),
          behavior: SnackBarBehavior.floating,
        ));
      }
    }
  }

  void _showCreateHouseDialog() {
    final controller = TextEditingController();
    bool loading = false;

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          title: const Text('Create a House'),
          content: TextField(
            controller: controller,
            autofocus: true,
            textCapitalization: TextCapitalization.words,
            decoration: const InputDecoration(
              labelText: 'Location / House Name',
              prefixIcon: Icon(Icons.location_on_outlined),
            ),
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
                      final loc = controller.text.trim();
                      if (loc.isEmpty) return;
                      setDialogState(() => loading = true);
                      try {
                        await ApiService.createHouse(loc);
                        if (ctx.mounted) Navigator.pop(ctx);
                        _reconnectForHouse();
                        if (mounted) setState(() {});
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
                          strokeWidth: 2, color: Colors.white))
                  : const Text('Create'),
            ),
          ],
        ),
      ),
    );
  }

  void _showJoinHouseDialog() {
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
              FilledButton.icon(
                onPressed: loading
                    ? null
                    : () {
                        Navigator.pop(ctx);
                        _openQrScanner();
                      },
                icon: const Icon(Icons.qr_code_scanner_rounded),
                label: const Text('Scan QR Code'),
                style: FilledButton.styleFrom(
                  minimumSize: const Size(double.infinity, 48),
                ),
              ),
              const SizedBox(height: 16),
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
              const SizedBox(height: 16),
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
                      final id =
                          int.tryParse(houseIdCtrl.text.trim());
                      final pin = pinCtrl.text.trim();
                      if (id == null || pin.length != 6) {
                        ScaffoldMessenger.of(ctx)
                            .showSnackBar(const SnackBar(
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
                        _reconnectForHouse();
                        if (mounted) setState(() {});
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
                          strokeWidth: 2, color: Colors.white))
                  : const Text('Join'),
            ),
          ],
        ),
      ),
    );
  }

  void _openQrScanner() {
    bool processed = false;
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => Scaffold(
          appBar: AppBar(title: const Text('Scan Invite QR')),
          body: MobileScanner(
            onDetect: (capture) async {
              if (processed) return;
              final barcode = capture.barcodes.firstOrNull;
              if (barcode?.rawValue == null) return;
              try {
                final data = jsonDecode(barcode!.rawValue!)
                    as Map<String, dynamic>;
                final houseId = data['house_id'] as int;
                final pin = data['pin'] as String;
                processed = true;
                Navigator.pop(context);
                await ApiService.joinHouse(houseId, pin);
                _reconnectForHouse();
                if (mounted) setState(() {});
              } catch (e) {
                if (mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                    content: Text(e
                        .toString()
                        .replaceFirst('Exception: ', '')),
                    behavior: SnackBarBehavior.floating,
                  ));
                }
              }
            },
          ),
        ),
      ),
    );
  }

  // ── Build ──────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    return Scaffold(
      appBar: AppBar(
        title: _buildHouseDropdown(cs),
        centerTitle: false,
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
            icon: Icon(Icons.chat_outlined),
            selectedIcon: Icon(Icons.chat_rounded),
            label: 'Chat',
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
  Widget _buildHouseDropdown(ColorScheme cs) {
    return DropdownButtonHideUnderline(
      child: DropdownButton<int>(
        value: ApiService.houseId,
        isDense: true,
        style: Theme.of(context).textTheme.titleLarge?.copyWith(
              fontWeight: FontWeight.w800,
            ),
        icon: Icon(Icons.arrow_drop_down_rounded,
            color: cs.onSurface),
        items: [
          // All houses
          ...ApiService.houses.map((h) => DropdownMenuItem<int>(
                value: h['house_id'] as int,
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.home_rounded,
                        size: 18,
                        color: h['is_active'] == true
                            ? cs.primary
                            : cs.onSurfaceVariant),
                    const SizedBox(width: 8),
                    Text(h['location'] ?? 'House ${h['house_id']}'),
                  ],
                ),
              )),
          // Divider item
          const DropdownMenuItem<int>(
            enabled: false,
            value: -999,
            child: Divider(),
          ),
          // Create house
          const DropdownMenuItem<int>(
            value: -1,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text('🏠', style: TextStyle(fontSize: 16)),
                SizedBox(width: 8),
                Text('Create House'),
              ],
            ),
          ),
          // Join house
          const DropdownMenuItem<int>(
            value: -2,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text('➕', style: TextStyle(fontSize: 16)),
                SizedBox(width: 8),
                Text('Join House'),
              ],
            ),
          ),
        ],
        onChanged: _onHouseSelected,
      ),
    );
  }
}
