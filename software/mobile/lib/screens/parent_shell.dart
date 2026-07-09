import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import '../services/api_service.dart';
import '../theme/accents.dart';
import 'home_tab.dart';
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
  int _unseenMentions = 0;
  StreamSubscription<void>? _mentionSub;
  static const int _chatTabIndex = 2;

  // Keep tab pages alive across switches. Home replaces the old Devices tab as
  // the primary control surface; Chat stays at index 2.
  late final List<Widget> _tabs = [
    HomeTab(
      onAskMaya: () {
        setState(() => _tabIndex = _chatTabIndex);
        _markChatSeen();
      },
      onHouseSelected: _onHouseSelected,
      onCreateHouse: _showCreateHouseDialog,
      onJoinHouse: _showJoinHouseDialog,
    ),
    const ChildrenTab(),
    const ChatTab(),
    const DeviceManagementTab(),
    const SettingsTab(),
  ];

  @override
  void initState() {
    super.initState();
    _connectWebSocket();
    _refreshMentions();
    _mentionSub = ApiService.mentionEvents.listen((_) => _refreshMentions());
  }

  @override
  void dispose() {
    _reconnectTimer?.cancel();
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

  // ── Clear chat (master only) ───────────────────────────────────
  Future<void> _confirmClearChat() async {
    final houseId = ApiService.houseId;
    if (houseId == null) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Clear chat?'),
        content: const Text(
            'This permanently deletes all messages in this house for everyone. '
            'This cannot be undone.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          FilledButton(
            style: FilledButton.styleFrom(
                backgroundColor: Theme.of(ctx).colorScheme.error),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Clear'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ApiService.clearChat(houseId);
      // The server broadcasts chat_cleared; the chat tab wipes itself on receipt.
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(e.toString().replaceFirst('Exception: ', '')),
          behavior: SnackBarBehavior.floating,
        ));
      }
    }
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
          } else if (type == 'device_update' ||
              type == 'device_offline' ||
              type == 'child_location') {
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

  /// Rebuild the whole shell after the active house changes, so every tab
  /// refetches instead of showing the previous house's cached data.
  void _reloadShell() {
    if (!mounted) return;
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => const ParentShell()),
    );
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
      _reloadShell();
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
                        _reloadShell();
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
                        _reloadShell();
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
                _reloadShell();
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

  String _getTabSubtitle() {
    switch (_tabIndex) {
      case 0:
        final hour = DateTime.now().hour;
        if (hour < 12) return 'Good morning';
        if (hour < 17) return 'Good afternoon';
        if (hour < 22) return 'Good evening';
        return 'Good night';
      case 1:
        return 'Family Management';
      case 2:
        return 'House Messages';
      case 3:
        return 'Device Center';
      case 4:
        return 'Preferences';
      default:
        return 'Maya Smart Home';
    }
  }

  // ── Build ──────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    return Scaffold(
      appBar: AppBar(
        titleSpacing: 20,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              _getTabSubtitle(),
              style: TextStyle(
                fontSize: 12.5,
                fontWeight: FontWeight.w500,
                color: Colors.white.withOpacity(0.55),
              ),
            ),
            const SizedBox(height: 2),
            Text(
              ApiService.activeHouse?['location'] ?? 'My Home',
              style: const TextStyle(
                fontSize: 21,
                fontWeight: FontWeight.w800,
                color: Colors.white,
                letterSpacing: -0.3,
              ),
            ),
          ],
        ),
        centerTitle: false,
        actions: [
          // Clear chat — house master only, while viewing the Chat tab
          if (_tabIndex == _chatTabIndex &&
              ApiService.activeHouse?['is_master'] == true)
            IconButton(
              tooltip: 'Clear chat',
              icon: const Icon(Icons.delete_sweep_outlined),
              onPressed: _confirmClearChat,
            ),
          // WebSocket status dot
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 7,
                height: 7,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: _wsConnected ? Colors.green : cs.error,
                  boxShadow: [
                    BoxShadow(
                      color: (_wsConnected ? Colors.green : cs.error)
                          .withOpacity(0.5),
                      blurRadius: 4,
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 5),
              Text(
                _wsConnected ? 'Live' : 'Offline',
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: cs.onSurfaceVariant,
                      fontSize: 10.5,
                    ),
              ),
            ],
          ),
          const SizedBox(width: 12),
          // Avatar dropdown with house switching & theme picker
          ListenableBuilder(
            listenable: ThemeController.instance,
            builder: (context, _) {
              final accent = ThemeController.instance.accent;
              final name = ApiService.userName.isEmpty ? 'there' : ApiService.userName;
              final initials = name.trim().isEmpty
                  ? 'ME'
                  : name.trim().split(' ').map((w) => w[0]).take(2).join().toUpperCase();

              return PopupMenuButton<dynamic>(
                offset: const Offset(0, 50),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                color: const Color(0xFF1A1F35),
                child: Container(
                  width: 36,
                  height: 36,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: LinearGradient(
                      colors: [accent.accent, accent.orbs.first],
                    ),
                    boxShadow: [
                      BoxShadow(
                        color: accent.accent.withOpacity(0.3),
                        blurRadius: 8,
                        spreadRadius: -1,
                      ),
                    ],
                  ),
                  child: Text(
                    initials,
                    style: TextStyle(
                      fontWeight: FontWeight.w800,
                      color: accent.onAccent,
                      fontSize: 11,
                    ),
                  ),
                ),
                itemBuilder: (ctx) => [
                  // Houses section
                  const PopupMenuItem(
                    enabled: false,
                    height: 32,
                    child: Text('HOUSES',
                        style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w700,
                            letterSpacing: 1.5,
                            color: Colors.white38)),
                  ),
                  ...ApiService.houses.map((h) {
                    final isActive = h['house_id'] == ApiService.houseId;
                    return PopupMenuItem<int>(
                      value: h['house_id'] as int,
                      child: Row(
                        children: [
                          Icon(
                            isActive ? Icons.home_rounded : Icons.home_outlined,
                            size: 18,
                            color: isActive ? accent.accent : Colors.white54,
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Text(
                              h['location'] ?? 'House ${h['house_id']}',
                              style: TextStyle(
                                color: isActive ? accent.accent : Colors.white,
                                fontWeight: isActive ? FontWeight.w700 : FontWeight.w500,
                              ),
                            ),
                          ),
                          if (isActive)
                            Icon(Icons.check_rounded, size: 16, color: accent.accent),
                        ],
                      ),
                    );
                  }),
                  PopupMenuItem<String>(
                    value: 'create',
                    child: Row(
                      children: [
                        Icon(Icons.add_rounded, size: 18, color: Colors.white.withOpacity(0.6)),
                        const SizedBox(width: 10),
                        Text('Create House', style: TextStyle(color: Colors.white.withOpacity(0.7))),
                      ],
                    ),
                  ),
                  PopupMenuItem<String>(
                    value: 'join',
                    child: Row(
                      children: [
                        Icon(Icons.group_add_outlined, size: 18, color: Colors.white.withOpacity(0.6)),
                        const SizedBox(width: 10),
                        Text('Join House', style: TextStyle(color: Colors.white.withOpacity(0.7))),
                      ],
                    ),
                  ),
                  const PopupMenuDivider(),
                  // Theme section
                  const PopupMenuItem(
                    enabled: false,
                    height: 32,
                    child: Text('THEME',
                        style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w700,
                            letterSpacing: 1.5,
                            color: Colors.white38)),
                  ),
                  ...kAccentPresets.map((p) {
                    final active = p.id == accent.id;
                    return PopupMenuItem<AccentPreset>(
                      value: p,
                      child: Row(
                        children: [
                          Container(
                            width: 18,
                            height: 18,
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              color: p.accent,
                              border: Border.all(
                                color: active ? Colors.white : Colors.transparent,
                                width: 2,
                              ),
                              boxShadow: active
                                  ? [BoxShadow(color: p.accent.withOpacity(0.5), blurRadius: 8)]
                                  : null,
                            ),
                          ),
                          const SizedBox(width: 10),
                          Text(
                            p.label,
                            style: TextStyle(
                              color: active ? accent.accent : Colors.white,
                              fontWeight: active ? FontWeight.w700 : FontWeight.w500,
                            ),
                          ),
                        ],
                      ),
                    );
                  }),
                ],
                onSelected: (value) {
                  if (value is int) {
                    _onHouseSelected(value);
                  } else if (value == 'create') {
                    _showCreateHouseDialog();
                  } else if (value == 'join') {
                    _showJoinHouseDialog();
                  } else if (value is AccentPreset) {
                    ThemeController.instance.setAccent(value);
                  }
                },
              );
            },
          ),
          const SizedBox(width: 16),
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
            icon: Icon(Icons.home_outlined),
            selectedIcon: Icon(Icons.home_rounded),
            label: 'Home',
          ),
          const NavigationDestination(
            icon: Icon(Icons.people_outline_rounded),
            selectedIcon: Icon(Icons.people_rounded),
            label: 'Children',
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
            icon: Icon(Icons.settings_remote_outlined),
            selectedIcon: Icon(Icons.settings_remote_rounded),
            label: 'Device',
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
