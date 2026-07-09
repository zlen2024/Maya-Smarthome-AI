import 'dart:async';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../services/api_service.dart';
import '../widgets/glass.dart';

/// Children management tab (Parent-only).
/// Lists child accounts with permissions, homework, screen limits
/// and last-known location.
class ChildrenTab extends StatefulWidget {
  const ChildrenTab({super.key});

  @override
  State<ChildrenTab> createState() => _ChildrenTabState();
}

class _ChildrenTabState extends State<ChildrenTab>
    with AutomaticKeepAliveClientMixin {
  List<dynamic> _children = [];
  List<dynamic> _devices = [];
  List<dynamic> _relays = [];
  List<dynamic> _permissions = [];
  bool _loading = true;
  StreamSubscription? _broadcastSub;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _fetchAll();
    _broadcastSub = ApiService.broadcasts.listen((data) {
      if (data['type'] != 'child_location' || !mounted) return;
      final idx =
          _children.indexWhere((c) => c['child_id'] == data['child_id']);
      if (idx == -1) return;
      setState(() {
        _children[idx]['last_lat'] = data['lat'];
        _children[idx]['last_lng'] = data['lng'];
        _children[idx]['last_seen_at'] = data['at'];
      });
    });
  }

  @override
  void dispose() {
    _broadcastSub?.cancel();
    super.dispose();
  }

  Future<void> _fetchAll() async {
    try {
      final results = await Future.wait([
        ApiService.getChildren(),
        ApiService.getDevices(),
        ApiService.getRelays(),
        ApiService.getPermissions(),
      ]);
      if (mounted) {
        setState(() {
          _children = results[0];
          _devices = results[1];
          _relays = results[2];
          _permissions = results[3];
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _loading = false);
    }
  }

  // ── Add Child Dialog ───────────────────────────────────────────
  Future<void> _showAddChildDialog() async {
    final nameCtrl = TextEditingController();
    final pinCtrl = TextEditingController();

    final result = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Add Child Account'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: nameCtrl,
              decoration: const InputDecoration(
                labelText: 'Child Name',
                prefixIcon: Icon(Icons.person_outline),
              ),
              textCapitalization: TextCapitalization.words,
            ),
            const SizedBox(height: 12),
            TextField(
              controller: pinCtrl,
              decoration: const InputDecoration(
                labelText: '4-Digit PIN',
                prefixIcon: Icon(Icons.pin_outlined),
                counterText: '',
              ),
              keyboardType: TextInputType.number,
              maxLength: 4,
              obscureText: true,
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Create'),
          ),
        ],
      ),
    );

    if (result == true) {
      final name = nameCtrl.text.trim();
      final pin = pinCtrl.text.trim();
      if (name.isEmpty || pin.length != 4) {
        _snack('Please enter a name and 4-digit PIN');
        return;
      }
      try {
        final data = await ApiService.createChild(name, pin);
        _snack('Created ${data['name']}! Child ID: ${data['child_id']}');
        _fetchAll();
      } catch (e) {
        _snack(e.toString().replaceFirst('Exception: ', ''));
      }
    }
  }

  // ── Permissions Bottom Sheet ───────────────────────────────────
  Future<void> _showPermissionsSheet(dynamic child) async {
    final childId = child['child_id'] as int;
    final childName = child['name'] as String;

    await showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      builder: (ctx) {
        return _PermissionsSheet(
          childId: childId,
          childName: childName,
          devices: _devices,
          relays: _relays,
          permissions: _permissions,
          onChanged: () => _fetchAll(),
        );
      },
    );
  }

  // ── Screen Limit Dialog ────────────────────────────────────────
  Future<void> _showScreenLimitDialog(dynamic child) async {
    final ctrl = TextEditingController(
        text: (child['daily_screen_limit_min'] ?? '').toString());
    final result = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Screen limit: ${child['name']}'),
        content: TextField(
          controller: ctrl,
          decoration: const InputDecoration(
            labelText: 'Daily limit (minutes)',
            helperText: 'Leave empty for no limit',
            prefixIcon: Icon(Icons.timer_outlined),
          ),
          keyboardType: TextInputType.number,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, ctrl.text.trim()),
            child: const Text('Save'),
          ),
        ],
      ),
    );

    if (result == null) return;
    final limit = result.isEmpty ? null : int.tryParse(result);
    if (result.isNotEmpty && (limit == null || limit < 0)) {
      _snack('Enter a valid number of minutes');
      return;
    }
    try {
      await ApiService.setScreenLimit(child['child_id'] as int, limit);
      _snack(limit == null
          ? 'Screen limit removed'
          : 'Screen limit set to $limit min/day');
      _fetchAll();
    } catch (e) {
      _snack(e.toString().replaceFirst('Exception: ', ''));
    }
  }

  // ── Homework Bottom Sheet ──────────────────────────────────────
  Future<void> _showHomeworkSheet(dynamic child) async {
    await showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      builder: (ctx) => _HomeworkSheet(
        childId: child['child_id'] as int,
        childName: child['name'] as String,
      ),
    );
  }

  // ── Location helpers ───────────────────────────────────────────
  String _lastSeenText(dynamic child) {
    final at = child['last_seen_at'];
    if (at == null) return 'Location: never reported';
    final t = DateTime.tryParse(at);
    if (t == null) return 'Location: unknown';
    final diff = DateTime.now().toUtc().difference(t.toUtc());
    String ago;
    if (diff.inMinutes < 1) {
      ago = 'just now';
    } else if (diff.inMinutes < 60) {
      ago = '${diff.inMinutes} min ago';
    } else if (diff.inHours < 24) {
      ago = '${diff.inHours} h ago';
    } else {
      ago = '${diff.inDays} d ago';
    }
    return 'Last seen $ago';
  }

  String _screenTimeText(dynamic child) {
    final st = child['screen_time'];
    if (st == null) return '';
    final limit = child['daily_screen_limit_min'];
    final used = st['total_min'];
    return '  ·  Screen: $used${limit != null ? '/$limit' : ''} min (${st['date']})';
  }

  Future<void> _openInMaps(dynamic child) async {
    final lat = child['last_lat'], lng = child['last_lng'];
    if (lat == null || lng == null) return;
    final uri = Uri.parse(
        'https://www.google.com/maps/search/?api=1&query=$lat,$lng');
    if (!await launchUrl(uri, mode: LaunchMode.externalApplication)) {
      _snack('Could not open maps');
    }
  }

  void _snack(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..clearSnackBars()
      ..showSnackBar(SnackBar(
        content: Text(msg),
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ));
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

    return Scaffold(
      body: _children.isEmpty
          ? Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.people_outline_rounded,
                      size: 56,
                      color: cs.onSurfaceVariant.withOpacity(0.35)),
                  const SizedBox(height: 12),
                  Text('No child accounts',
                      style: tt.titleMedium
                          ?.copyWith(color: cs.onSurfaceVariant)),
                  const SizedBox(height: 4),
                  Text('Tap + to create a child profile.',
                      style: tt.bodySmall
                          ?.copyWith(color: cs.onSurfaceVariant)),
                ],
              ),
            )
          : RefreshIndicator(
              onRefresh: _fetchAll,
              child: ListView.builder(
                padding: const EdgeInsets.all(16),
                itemCount: _children.length,
                itemBuilder: (ctx, i) {
                  final child = _children[i];
                  final hasLocation = child['last_lat'] != null;
                  final limit = child['daily_screen_limit_min'];
                  return Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: GlassSurface(
                      padding: EdgeInsets.zero,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          ListTile(
                            contentPadding: const EdgeInsets.only(
                                left: 18, right: 8, top: 4),
                            leading: CircleAvatar(
                              backgroundColor: cs.primaryContainer,
                              child: Icon(Icons.child_care_rounded,
                                  color: cs.onPrimaryContainer),
                            ),
                            title: Text(child['name'] ?? 'Child',
                                style:
                                    const TextStyle(fontWeight: FontWeight.w700)),
                            subtitle: Text(
                                'ID: ${child['child_id']}'
                                '${limit != null ? '  ·  $limit min/day' : ''}',
                                style: tt.labelSmall?.copyWith(
                                    color: cs.onSurfaceVariant,
                                    fontFamily: 'monospace')),
                            trailing: hasLocation
                                ? TextButton.icon(
                                    onPressed: () => _openInMaps(child),
                                    icon: const Icon(Icons.place_outlined,
                                        size: 18),
                                    label: const Text('Map'),
                                  )
                                : null,
                          ),
                          Padding(
                            padding: const EdgeInsets.only(left: 18, bottom: 4),
                            child: Text(
                                '${_lastSeenText(child)}${_screenTimeText(child)}',
                                style: tt.labelSmall
                                    ?.copyWith(color: cs.onSurfaceVariant)),
                          ),
                          Padding(
                            padding:
                                const EdgeInsets.only(left: 10, bottom: 6),
                            child: Wrap(
                              spacing: 4,
                              children: [
                                TextButton(
                                  onPressed: () => _showPermissionsSheet(child),
                                  child: const Text('Permissions'),
                                ),
                                TextButton(
                                  onPressed: () => _showHomeworkSheet(child),
                                  child: const Text('Homework'),
                                ),
                                TextButton(
                                  onPressed: () => _showScreenLimitDialog(child),
                                  child: const Text('Screen limit'),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                  );
                },
              ),
            ),
      floatingActionButton: FloatingActionButton(
        onPressed: _showAddChildDialog,
        tooltip: 'Add Child',
        child: const Icon(Icons.person_add_rounded),
      ),
    );
  }
}

// ── Homework Sheet ───────────────────────────────────────────────
class _HomeworkSheet extends StatefulWidget {
  final int childId;
  final String childName;

  const _HomeworkSheet({required this.childId, required this.childName});

  @override
  State<_HomeworkSheet> createState() => _HomeworkSheetState();
}

class _HomeworkSheetState extends State<_HomeworkSheet> {
  List<dynamic> _homework = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _fetch();
  }

  Future<void> _fetch() async {
    try {
      final hw = await ApiService.getHomework(childId: widget.childId);
      if (mounted) {
        setState(() {
          _homework = hw;
          _loading = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _addHomework() async {
    final titleCtrl = TextEditingController();
    final descCtrl = TextEditingController();
    final dueCtrl = TextEditingController();

    final result = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Assign Homework'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: titleCtrl,
              decoration: const InputDecoration(labelText: 'Title'),
              textCapitalization: TextCapitalization.sentences,
            ),
            const SizedBox(height: 12),
            TextField(
              controller: descCtrl,
              decoration:
                  const InputDecoration(labelText: 'Details (optional)'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: dueCtrl,
              readOnly: true,
              decoration: const InputDecoration(
                labelText: 'Due date (optional)',
                prefixIcon: Icon(Icons.event_outlined),
              ),
              onTap: () async {
                final now = DateTime.now();
                final picked = await showDatePicker(
                  context: ctx,
                  initialDate: now,
                  firstDate: now,
                  lastDate: now.add(const Duration(days: 365)),
                );
                if (picked != null) {
                  dueCtrl.text =
                      picked.toIso8601String().substring(0, 10);
                }
              },
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Assign'),
          ),
        ],
      ),
    );

    if (result == true && titleCtrl.text.trim().isNotEmpty) {
      try {
        await ApiService.createHomework(
          widget.childId,
          titleCtrl.text.trim(),
          description: descCtrl.text.trim(),
          dueDate: dueCtrl.text.isEmpty ? null : dueCtrl.text,
        );
        _fetch();
      } catch (_) {}
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;

    return Padding(
      padding:
          EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
      child: DraggableScrollableSheet(
        initialChildSize: 0.55,
        maxChildSize: 0.85,
        minChildSize: 0.35,
        expand: false,
        builder: (ctx, scrollCtrl) => Column(
          children: [
            Container(
              width: 36,
              height: 5,
              margin: const EdgeInsets.only(top: 12, bottom: 8),
              decoration: BoxDecoration(
                color: cs.onSurfaceVariant.withOpacity(0.25),
                borderRadius: BorderRadius.circular(3),
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: Row(
                children: [
                  Icon(Icons.menu_book_rounded, color: cs.primary),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      'Homework: ${widget.childName}',
                      style:
                          tt.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                    ),
                  ),
                  IconButton.filledTonal(
                    onPressed: _addHomework,
                    icon: const Icon(Icons.add_rounded),
                    tooltip: 'Assign homework',
                  ),
                ],
              ),
            ),
            const SizedBox(height: 8),
            const Divider(),
            Expanded(
              child: _loading
                  ? const Center(child: CircularProgressIndicator())
                  : _homework.isEmpty
                      ? Center(
                          child: Text('No homework assigned',
                              style: tt.bodyMedium
                                  ?.copyWith(color: cs.onSurfaceVariant)),
                        )
                      : ListView.builder(
                          controller: scrollCtrl,
                          padding: const EdgeInsets.symmetric(
                              horizontal: 16, vertical: 8),
                          itemCount: _homework.length,
                          itemBuilder: (ctx, i) {
                            final hw = _homework[i];
                            final done = hw['is_done'] == true;
                            return Card(
                              color: cs.surfaceContainerLow,
                              margin: const EdgeInsets.only(bottom: 8),
                              child: ListTile(
                                leading: Icon(
                                  done
                                      ? Icons.check_circle_rounded
                                      : Icons.radio_button_unchecked_rounded,
                                  color:
                                      done ? Colors.green : cs.onSurfaceVariant,
                                ),
                                title: Text(hw['title'] ?? '',
                                    style: TextStyle(
                                      fontWeight: FontWeight.w600,
                                      decoration: done
                                          ? TextDecoration.lineThrough
                                          : null,
                                    )),
                                subtitle: hw['due_date'] != null
                                    ? Text('Due ${hw['due_date']}',
                                        style: tt.labelSmall?.copyWith(
                                            color: cs.onSurfaceVariant))
                                    : null,
                                trailing: IconButton(
                                  icon: const Icon(Icons.delete_outline),
                                  onPressed: () async {
                                    try {
                                      await ApiService.deleteHomework(
                                          hw['hw_id'] as int);
                                      _fetch();
                                    } catch (_) {}
                                  },
                                ),
                              ),
                            );
                          },
                        ),
            ),
          ],
        ),
      ),
    );
  }
}

// ── Permissions Sheet ────────────────────────────────────────────
class _PermissionsSheet extends StatefulWidget {
  final int childId;
  final String childName;
  final List<dynamic> devices;
  final List<dynamic> relays;
  final List<dynamic> permissions;
  final VoidCallback onChanged;

  const _PermissionsSheet({
    required this.childId,
    required this.childName,
    required this.devices,
    required this.relays,
    required this.permissions,
    required this.onChanged,
  });

  @override
  State<_PermissionsSheet> createState() => _PermissionsSheetState();
}

class _PermissionsSheetState extends State<_PermissionsSheet> {
  late List<dynamic> _perms;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _perms = List.from(widget.permissions);
  }

  Future<void> _togglePerm(dynamic relay, bool allowed) async {
    setState(() => _saving = true);
    try {
      final existing = _perms.firstWhere(
        (p) =>
            p['child_id'] == widget.childId &&
            p['relay_id'] == relay['relay_id'],
        orElse: () => null,
      );

      if (existing != null) {
        await ApiService.updatePermission(
            existing['permission_id'] as int, allowed);
        existing['is_allowed'] = allowed;
      } else {
        await ApiService.createPermission(
            widget.childId, relay['relay_id'] as int, allowed);
      }

      // Re-fetch permissions
      final freshPerms = await ApiService.getPermissions();
      setState(() => _perms = freshPerms);
      widget.onChanged();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
              content:
                  Text(e.toString().replaceFirst('Exception: ', ''))),
        );
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;

    return Padding(
      padding: EdgeInsets.only(
        bottom: MediaQuery.of(context).viewInsets.bottom,
      ),
      child: DraggableScrollableSheet(
        initialChildSize: 0.55,
        maxChildSize: 0.85,
        minChildSize: 0.35,
        expand: false,
        builder: (ctx, scrollCtrl) => Column(
          children: [
            // Handle bar
            Container(
              width: 36,
              height: 5,
              margin: const EdgeInsets.only(top: 12, bottom: 8),
              decoration: BoxDecoration(
                color: cs.onSurfaceVariant.withOpacity(0.25),
                borderRadius: BorderRadius.circular(3),
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: Row(
                children: [
                  Icon(Icons.lock_outline_rounded, color: cs.primary),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      'Permissions: ${widget.childName}',
                      style:
                          tt.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                    ),
                  ),
                  if (_saving)
                    const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2)),
                ],
              ),
            ),
            const SizedBox(height: 8),
            const Divider(),
            Expanded(
              child: widget.relays.isEmpty
                  ? Center(
                      child: Text('No channels available',
                          style: tt.bodyMedium
                              ?.copyWith(color: cs.onSurfaceVariant)),
                    )
                  : ListView.builder(
                      controller: scrollCtrl,
                      padding: const EdgeInsets.symmetric(
                          horizontal: 16, vertical: 8),
                      itemCount: widget.relays.length,
                      itemBuilder: (ctx, i) {
                        final relay = widget.relays[i];
                        final device = widget.devices.firstWhere(
                          (d) => d['device_id'] == relay['device_id'],
                          orElse: () =>
                              {'name': 'Unknown', 'device_id': '?'},
                        );

                        final perm = _perms.firstWhere(
                          (p) =>
                              p['child_id'] == widget.childId &&
                              p['relay_id'] == relay['relay_id'],
                          orElse: () => null,
                        );
                        final allowed =
                            perm != null && perm['is_allowed'] == true;

                        return Card(
                          color: cs.surfaceContainerLow,
                          margin: const EdgeInsets.only(bottom: 8),
                          child: ListTile(
                            leading: Icon(
                              Icons.electrical_services_rounded,
                              color: allowed ? cs.primary : cs.onSurfaceVariant,
                            ),
                            title: Text(
                              '${relay['name']} (CH${relay['channel_number']})',
                              style: const TextStyle(
                                  fontWeight: FontWeight.w600),
                            ),
                            subtitle: Text(device['name'],
                                style: tt.labelSmall
                                    ?.copyWith(color: cs.onSurfaceVariant)),
                            trailing: Switch.adaptive(
                              value: allowed,
                              onChanged: _saving
                                  ? null
                                  : (v) => _togglePerm(relay, v),
                            ),
                          ),
                        );
                      },
                    ),
            ),
          ],
        ),
      ),
    );
  }
}
