import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:qr_flutter/qr_flutter.dart';
import '../services/api_service.dart';
import 'login_screen.dart';

/// Settings tab — user info, house info, house management, logout, app version.
/// Shared between Parent and Child shells.
class SettingsTab extends StatefulWidget {
  const SettingsTab({super.key});

  @override
  State<SettingsTab> createState() => _SettingsTabState();
}

class _SettingsTabState extends State<SettingsTab> {
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;
    final isParent = !ApiService.isChild;
    final isMaster = ApiService.activeHouse?['is_master'] == true;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        // ── User Profile Card ────────────────────────────────────
        Card(
          color: cs.surfaceContainerLow,
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Row(
              children: [
                CircleAvatar(
                  radius: 28,
                  backgroundColor: cs.primaryContainer,
                  child: Text(
                    ApiService.userName.isNotEmpty
                        ? ApiService.userName[0].toUpperCase()
                        : '?',
                    style: tt.headlineSmall?.copyWith(
                      fontWeight: FontWeight.w800,
                      color: cs.onPrimaryContainer,
                    ),
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        ApiService.userName.isNotEmpty
                            ? ApiService.userName
                            : 'User',
                        style:
                            tt.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                      ),
                      const SizedBox(height: 4),
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 10, vertical: 3),
                        decoration: BoxDecoration(
                          color: ApiService.isChild
                              ? Colors.green.withOpacity(0.12)
                              : cs.primary.withOpacity(0.12),
                          borderRadius: BorderRadius.circular(20),
                        ),
                        child: Text(
                          ApiService.isChild ? 'Child' : 'Parent',
                          style: tt.labelSmall?.copyWith(
                            fontWeight: FontWeight.w700,
                            color: ApiService.isChild
                                ? Colors.green
                                : cs.primary,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),

        // ── House Info Card ──────────────────────────────────────
        Card(
          color: cs.surfaceContainerLow,
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(Icons.home_rounded, color: cs.primary, size: 22),
                    const SizedBox(width: 10),
                    Text('House Information',
                        style: tt.titleSmall
                            ?.copyWith(fontWeight: FontWeight.w700)),
                  ],
                ),
                const SizedBox(height: 14),
                _infoTile('House ID', '${ApiService.houseId ?? '—'}', cs, tt),
                _infoTile(
                    'Location',
                    ApiService.activeHouse?['location'] ?? '—',
                    cs,
                    tt),
                _infoTile(
                    'Role',
                    isMaster ? 'Master (Owner)' : 'Member',
                    cs,
                    tt),
                _infoTile('Server', ApiService.baseUrl, cs, tt),
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),

        // ── House Management (Parent only) ───────────────────────
        if (isParent) ...[
          // Invite Family Member
          Card(
            color: cs.surfaceContainerLow,
            clipBehavior: Clip.antiAlias,
            child: ListTile(
              leading: Icon(Icons.person_add_rounded, color: cs.primary),
              title: const Text('Invite Family Member'),
              subtitle: const Text('Share QR code or PIN'),
              trailing: const Icon(Icons.chevron_right_rounded),
              onTap: () => _showInviteSheet(context),
            ),
          ),
          const SizedBox(height: 8),

          // House Members
          Card(
            color: cs.surfaceContainerLow,
            clipBehavior: Clip.antiAlias,
            child: ListTile(
              leading: Icon(Icons.group_rounded, color: cs.primary),
              title: const Text('House Members'),
              subtitle: const Text('View and manage members'),
              trailing: const Icon(Icons.chevron_right_rounded),
              onTap: () => _showMembersSheet(context),
            ),
          ),
          const SizedBox(height: 8),

          // Leave House (non-master only)
          if (!isMaster)
            Card(
              color: cs.surfaceContainerLow,
              clipBehavior: Clip.antiAlias,
              child: ListTile(
                leading: Icon(Icons.exit_to_app_rounded, color: cs.error),
                title: Text('Leave House',
                    style: TextStyle(color: cs.error)),
                subtitle: const Text('Remove yourself from this house'),
                onTap: () => _confirmLeaveHouse(context),
              ),
            ),
          if (!isMaster) const SizedBox(height: 8),
        ],

        const SizedBox(height: 12),

        // ── Logout Button ────────────────────────────────────────
        FilledButton.icon(
          onPressed: () => _confirmLogout(context),
          icon: const Icon(Icons.logout_rounded),
          label: const Text('Logout'),
          style: FilledButton.styleFrom(
            backgroundColor: cs.error,
            foregroundColor: cs.onError,
          ),
        ),
        const SizedBox(height: 24),

        // ── App Info ─────────────────────────────────────────────
        Center(
          child: Text(
            'Maya Smart Home v1.0.0',
            style: tt.labelSmall?.copyWith(color: cs.onSurfaceVariant),
          ),
        ),
      ],
    );
  }

  Widget _infoTile(
      String label, String value, ColorScheme cs, TextTheme tt) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 90,
            child: Text(label,
                style:
                    tt.labelSmall?.copyWith(color: cs.onSurfaceVariant)),
          ),
          Expanded(
            child: Text(value,
                style: tt.bodySmall?.copyWith(
                  fontWeight: FontWeight.w600,
                  fontFamily: 'monospace',
                )),
          ),
        ],
      ),
    );
  }

  // ── Invite Sheet ───────────────────────────────────────────────
  void _showInviteSheet(BuildContext context) {
    final houseId = ApiService.houseId;
    if (houseId == null) return;

    String pin = ApiService.activeHouse?['join_pin'] ?? '------';
    bool regenerating = false;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSheetState) {
          final cs = Theme.of(ctx).colorScheme;
          final tt = Theme.of(ctx).textTheme;
          final qrData = jsonEncode({
            'house_id': houseId,
            'pin': pin,
          });

          return Padding(
            padding: EdgeInsets.only(
              left: 24,
              right: 24,
              top: 24,
              bottom: MediaQuery.of(ctx).padding.bottom + 24,
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                // Handle bar
                Container(
                  width: 40,
                  height: 4,
                  decoration: BoxDecoration(
                    color: cs.onSurfaceVariant.withOpacity(0.3),
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
                const SizedBox(height: 20),
                Text('Invite Family Member',
                    style: tt.titleLarge
                        ?.copyWith(fontWeight: FontWeight.w700)),
                const SizedBox(height: 8),
                Text('Scan this QR code or share the PIN below',
                    style: tt.bodySmall
                        ?.copyWith(color: cs.onSurfaceVariant)),
                const SizedBox(height: 24),

                // QR Code
                Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: QrImageView(
                    data: qrData,
                    version: QrVersions.auto,
                    size: 200,
                    backgroundColor: Colors.white,
                  ),
                ),
                const SizedBox(height: 24),

                // House ID & PIN
                Card(
                  color: cs.surfaceContainerHigh,
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      children: [
                        Row(
                          mainAxisAlignment:
                              MainAxisAlignment.spaceBetween,
                          children: [
                            Text('House ID',
                                style: tt.labelMedium?.copyWith(
                                    color: cs.onSurfaceVariant)),
                            SelectableText('$houseId',
                                style: tt.titleMedium?.copyWith(
                                    fontWeight: FontWeight.w700,
                                    fontFamily: 'monospace')),
                          ],
                        ),
                        const Divider(height: 20),
                        Row(
                          mainAxisAlignment:
                              MainAxisAlignment.spaceBetween,
                          children: [
                            Text('PIN',
                                style: tt.labelMedium?.copyWith(
                                    color: cs.onSurfaceVariant)),
                            Row(
                              children: [
                                SelectableText(pin,
                                    style: tt.titleMedium?.copyWith(
                                        fontWeight: FontWeight.w700,
                                        fontFamily: 'monospace',
                                        letterSpacing: 4)),
                                const SizedBox(width: 8),
                                IconButton(
                                  icon: const Icon(
                                      Icons.copy_rounded,
                                      size: 18),
                                  onPressed: () {
                                    Clipboard.setData(ClipboardData(
                                        text:
                                            'House ID: $houseId\nPIN: $pin'));
                                    ScaffoldMessenger.of(ctx)
                                        .showSnackBar(const SnackBar(
                                      content:
                                          Text('Copied to clipboard'),
                                      behavior:
                                          SnackBarBehavior.floating,
                                    ));
                                  },
                                  tooltip: 'Copy',
                                ),
                              ],
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 16),

                // Regenerate PIN button
                OutlinedButton.icon(
                  onPressed: regenerating
                      ? null
                      : () async {
                          setSheetState(() => regenerating = true);
                          try {
                            final newPin =
                                await ApiService.resetPin(houseId);
                            setSheetState(() {
                              pin = newPin;
                              regenerating = false;
                            });
                            // Update local activeHouse
                            if (ApiService.activeHouse != null) {
                              ApiService.activeHouse!['join_pin'] =
                                  newPin;
                            }
                          } catch (e) {
                            setSheetState(
                                () => regenerating = false);
                            if (ctx.mounted) {
                              ScaffoldMessenger.of(ctx)
                                  .showSnackBar(SnackBar(
                                content: Text(e
                                    .toString()
                                    .replaceFirst(
                                        'Exception: ', '')),
                                behavior:
                                    SnackBarBehavior.floating,
                              ));
                            }
                          }
                        },
                  icon: regenerating
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                              strokeWidth: 2))
                      : const Icon(Icons.refresh_rounded),
                  label: const Text('Regenerate PIN'),
                  style: OutlinedButton.styleFrom(
                    minimumSize: const Size(double.infinity, 48),
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }

  // ── Members Sheet ──────────────────────────────────────────────
  void _showMembersSheet(BuildContext context) {
    final houseId = ApiService.houseId;
    if (houseId == null) return;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      builder: (ctx) => _MembersSheet(houseId: houseId),
    );
  }

  // ── Leave House ────────────────────────────────────────────────
  Future<void> _confirmLeaveHouse(BuildContext context) async {
    final result = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Leave House'),
        content: const Text(
            'Are you sure you want to leave this house? You will need an invite to rejoin.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(ctx).colorScheme.error,
              foregroundColor: Theme.of(ctx).colorScheme.onError,
            ),
            child: const Text('Leave'),
          ),
        ],
      ),
    );

    if (result == true && context.mounted) {
      try {
        final houseId = ApiService.houseId;
        final accId = ApiService.accId;
        if (houseId != null && accId != null) {
          await ApiService.kickMember(houseId, accId);
          await ApiService.getHouses();
          if (context.mounted) {
            // Navigate back to re-evaluate
            Navigator.pushNamedAndRemoveUntil(
                context, '/', (_) => false);
          }
        }
      } catch (e) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content:
                Text(e.toString().replaceFirst('Exception: ', '')),
            behavior: SnackBarBehavior.floating,
          ));
        }
      }
    }
  }

  // ── Logout ─────────────────────────────────────────────────────
  Future<void> _confirmLogout(BuildContext context) async {
    final result = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Logout'),
        content: const Text('Are you sure you want to sign out?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(ctx).colorScheme.error,
              foregroundColor: Theme.of(ctx).colorScheme.onError,
            ),
            child: const Text('Logout'),
          ),
        ],
      ),
    );

    if (result == true && context.mounted) {
      await ApiService.logout();
      Navigator.pushAndRemoveUntil(
        context,
        MaterialPageRoute(builder: (_) => const LoginScreen()),
        (_) => false,
      );
    }
  }
}

// ── Members Sheet Widget ───────────────────────────────────────────
class _MembersSheet extends StatefulWidget {
  final int houseId;

  const _MembersSheet({required this.houseId});

  @override
  State<_MembersSheet> createState() => _MembersSheetState();
}

class _MembersSheetState extends State<_MembersSheet> {
  List<Map<String, dynamic>> _members = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _loadMembers();
  }

  Future<void> _loadMembers() async {
    setState(() => _loading = true);
    try {
      _members = await ApiService.getMembers(widget.houseId);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content:
              Text(e.toString().replaceFirst('Exception: ', '')),
          behavior: SnackBarBehavior.floating,
        ));
      }
    }
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _kickMember(int accId, String name) async {
    final result = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Remove Member'),
        content: Text('Remove $name from this house?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(ctx).colorScheme.error,
              foregroundColor: Theme.of(ctx).colorScheme.onError,
            ),
            child: const Text('Remove'),
          ),
        ],
      ),
    );

    if (result == true) {
      try {
        await ApiService.kickMember(widget.houseId, accId);
        _loadMembers();
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
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;
    final isMaster = ApiService.activeHouse?['is_master'] == true;

    return Padding(
      padding: EdgeInsets.only(
        left: 24,
        right: 24,
        top: 24,
        bottom: MediaQuery.of(context).padding.bottom + 24,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Handle bar
          Container(
            width: 40,
            height: 4,
            decoration: BoxDecoration(
              color: cs.onSurfaceVariant.withOpacity(0.3),
              borderRadius: BorderRadius.circular(2),
            ),
          ),
          const SizedBox(height: 20),
          Text('House Members',
              style:
                  tt.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 16),
          if (_loading)
            const Padding(
              padding: EdgeInsets.all(24),
              child: CircularProgressIndicator(),
            )
          else if (_members.isEmpty)
            Padding(
              padding: const EdgeInsets.all(24),
              child: Text('No members found',
                  style: tt.bodyMedium
                      ?.copyWith(color: cs.onSurfaceVariant)),
            )
          else
            ConstrainedBox(
              constraints: BoxConstraints(
                maxHeight: MediaQuery.of(context).size.height * 0.5,
              ),
              child: ListView.builder(
                shrinkWrap: true,
                itemCount: _members.length,
                itemBuilder: (context, index) {
                  final member = _members[index];
                  final name = member['name'] ?? 'Unknown';
                  final email = member['email'] ?? '';
                  final memberIsMaster =
                      member['is_master'] == true;
                  final memberId = member['acc_id'] as int?;

                  return ListTile(
                    leading: CircleAvatar(
                      backgroundColor: memberIsMaster
                          ? cs.primaryContainer
                          : cs.surfaceContainerHigh,
                      child: Text(
                        name.isNotEmpty
                            ? name[0].toUpperCase()
                            : '?',
                        style: TextStyle(
                          color: memberIsMaster
                              ? cs.onPrimaryContainer
                              : cs.onSurface,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                    title: Row(
                      children: [
                        Flexible(
                          child: Text(name,
                              overflow: TextOverflow.ellipsis),
                        ),
                        if (memberIsMaster) ...[
                          const SizedBox(width: 8),
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 8, vertical: 2),
                            decoration: BoxDecoration(
                              color: cs.primary.withOpacity(0.12),
                              borderRadius:
                                  BorderRadius.circular(12),
                            ),
                            child: Text('Owner',
                                style: tt.labelSmall?.copyWith(
                                  color: cs.primary,
                                  fontWeight: FontWeight.w700,
                                )),
                          ),
                        ],
                      ],
                    ),
                    subtitle: email.isNotEmpty
                        ? Text(email,
                            style: tt.bodySmall?.copyWith(
                                color: cs.onSurfaceVariant))
                        : null,
                    trailing: isMaster &&
                            !memberIsMaster &&
                            memberId != null
                        ? IconButton(
                            icon: Icon(Icons.person_remove_rounded,
                                color: cs.error),
                            tooltip: 'Remove',
                            onPressed: () =>
                                _kickMember(memberId, name),
                          )
                        : null,
                  );
                },
              ),
            ),
        ],
      ),
    );
  }
}
