import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../services/api_service.dart';

/// Child-facing task list: screen-time summary + homework assigned by
/// parents, checkable when done. Screen time is read from Android
/// UsageStats via the `maya/usage` platform channel and reported to the
/// server so parents can see it too.
class ChildTasksTab extends StatefulWidget {
  const ChildTasksTab({super.key});

  @override
  State<ChildTasksTab> createState() => _ChildTasksTabState();
}

class _ChildTasksTabState extends State<ChildTasksTab>
    with WidgetsBindingObserver {
  static const _usage = MethodChannel('maya/usage');

  List<dynamic> _homework = [];
  bool _loading = true;
  String? _error;

  bool? _usageGranted; // null = unknown (non-Android or not yet checked)
  int? _usedMin;
  int? _limitMin;
  Timer? _usageTimer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _fetch();
    _refreshUsage();
    _usageTimer =
        Timer.periodic(const Duration(minutes: 15), (_) => _refreshUsage());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _usageTimer?.cancel();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Re-check after the child returns from the usage-access Settings screen.
    if (state == AppLifecycleState.resumed) _refreshUsage();
  }

  String get _today {
    final now = DateTime.now();
    return '${now.year}-${now.month.toString().padLeft(2, '0')}'
        '-${now.day.toString().padLeft(2, '0')}';
  }

  Future<void> _refreshUsage() async {
    try {
      final granted = await _usage.invokeMethod<bool>('hasPermission');
      if (!mounted) return;
      setState(() => _usageGranted = granted);
      if (granted != true) return;

      final minutes = await _usage.invokeMethod<int>('getTodayUsageMinutes');
      if (minutes == null) return;
      await ApiService.reportScreenTime(_today, minutes);
      final me = await ApiService.getMyScreenTime(_today);
      if (mounted) {
        setState(() {
          _usedMin = me['used_min'];
          _limitMin = me['limit_min'];
        });
      }
    } catch (_) {} // non-Android platform or transient failure
  }

  Future<void> _fetch() async {
    try {
      final hw = await ApiService.getHomework();
      if (mounted) {
        setState(() {
          _homework = hw;
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

  Future<void> _toggleDone(dynamic hw, bool done) async {
    setState(() => hw['is_done'] = done); // optimistic
    try {
      await ApiService.setHomeworkDone(hw['hw_id'], done);
    } catch (_) {
      if (mounted) setState(() => hw['is_done'] = !done); // revert
    }
  }

  // ── Screen-time header ──────────────────────────────────────────
  Widget? _screenTimeCard(ColorScheme cs, TextTheme tt) {
    if (_usageGranted == null) return null; // channel unavailable
    if (_usageGranted == false) {
      return Card(
        margin: const EdgeInsets.fromLTRB(12, 12, 12, 0),
        color: cs.tertiaryContainer,
        child: ListTile(
          leading: Icon(Icons.hourglass_empty_rounded,
              color: cs.onTertiaryContainer),
          title: const Text('Enable usage access'),
          subtitle: const Text(
              'Needed to track your screen time. Tap to open settings.'),
          onTap: () => _usage.invokeMethod('openSettings'),
        ),
      );
    }
    if (_usedMin == null) return null;
    final limit = _limitMin;
    final remaining = limit != null ? (limit - _usedMin!).clamp(0, limit) : null;
    final overLimit = limit != null && _usedMin! >= limit;
    return Card(
      margin: const EdgeInsets.fromLTRB(12, 12, 12, 0),
      color: overLimit ? cs.errorContainer : cs.primaryContainer,
      child: ListTile(
        leading: Icon(Icons.timer_outlined,
            color: overLimit ? cs.onErrorContainer : cs.onPrimaryContainer),
        title: Text(
          limit == null
              ? 'Screen time today: $_usedMin min'
              : overLimit
                  ? 'Screen time is up for today!'
                  : 'Remaining today: $remaining min',
          style: const TextStyle(fontWeight: FontWeight.w700),
        ),
        subtitle: limit != null
            ? Text('Used $_usedMin of $limit min')
            : const Text('No daily limit set'),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;

    if (_loading) return const Center(child: CircularProgressIndicator());

    final header = _screenTimeCard(cs, tt);

    return Column(
      children: [
        if (header != null) header,
        Expanded(child: _buildHomeworkList(cs, tt)),
      ],
    );
  }

  Widget _buildHomeworkList(ColorScheme cs, TextTheme tt) {
    return RefreshIndicator(
      onRefresh: () async {
        await _fetch();
        await _refreshUsage();
      },
      child: _error != null
          ? ListView(children: [
              Padding(
                padding: const EdgeInsets.all(32),
                child: Text(_error!, textAlign: TextAlign.center),
              ),
            ])
          : _homework.isEmpty
              ? ListView(children: [
                  const SizedBox(height: 120),
                  Icon(Icons.task_alt_rounded, size: 56, color: cs.outline),
                  const SizedBox(height: 12),
                  Center(
                    child: Text('No homework — enjoy your day!',
                        style: tt.bodyLarge?.copyWith(color: cs.onSurfaceVariant)),
                  ),
                ])
              : ListView.builder(
                  padding: const EdgeInsets.all(12),
                  itemCount: _homework.length,
                  itemBuilder: (context, i) {
                    final hw = _homework[i];
                    final done = hw['is_done'] == true;
                    return Card(
                      margin: const EdgeInsets.only(bottom: 8),
                      child: CheckboxListTile(
                        value: done,
                        onChanged: (v) => _toggleDone(hw, v ?? false),
                        title: Text(
                          hw['title'] ?? '',
                          style: done
                              ? tt.bodyLarge?.copyWith(
                                  decoration: TextDecoration.lineThrough,
                                  color: cs.onSurfaceVariant)
                              : tt.bodyLarge,
                        ),
                        subtitle: (hw['description'] ?? '').isNotEmpty ||
                                hw['due_date'] != null
                            ? Text([
                                if ((hw['description'] ?? '').isNotEmpty)
                                  hw['description'],
                                if (hw['due_date'] != null)
                                  'Due ${hw['due_date']}',
                              ].join(' · '))
                            : null,
                        controlAffinity: ListTileControlAffinity.leading,
                      ),
                    );
                  },
                ),
    );
  }
}
