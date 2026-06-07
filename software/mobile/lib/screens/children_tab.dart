import 'package:flutter/material.dart';
import '../services/api_service.dart';

/// Children management tab (Parent-only).
/// Lists child accounts with permissions management.
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

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _fetchAll();
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
                  return Card(
                    margin: const EdgeInsets.only(bottom: 12),
                    color: cs.surfaceContainerLow,
                    child: ListTile(
                      contentPadding: const EdgeInsets.symmetric(
                          horizontal: 18, vertical: 8),
                      leading: CircleAvatar(
                        backgroundColor: cs.primaryContainer,
                        child: Icon(Icons.child_care_rounded,
                            color: cs.onPrimaryContainer),
                      ),
                      title: Text(child['name'] ?? 'Child',
                          style: const TextStyle(fontWeight: FontWeight.w700)),
                      subtitle: Text('ID: ${child['child_id']}',
                          style: tt.labelSmall?.copyWith(
                              color: cs.onSurfaceVariant,
                              fontFamily: 'monospace')),
                      trailing: FilledButton.tonal(
                        onPressed: () => _showPermissionsSheet(child),
                        child: const Text('Permissions'),
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
