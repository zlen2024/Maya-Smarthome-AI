import 'package:flutter/material.dart';

/// One control, chosen by a capability's `kind` (PROTOCOL.md §5.2).
///
/// This widget is the whole point of protocol 2 on the app side: the UI is
/// chosen by `kind`, never by device model, so a contributor's new hardware
/// renders here without this file changing. Ten kinds are a closed set — a
/// `kind` this build has never heard of degrades to a read-only value rather
/// than disappearing (§11), so an older app still shows a newer device's
/// readings.
///
/// It owns no state of its own beyond what a slider needs while a thumb is
/// down: the value comes from the parent's copy of the device state, and
/// [onSet] is expected to update that and push to the server.
class CapabilityControl extends StatefulWidget {
  const CapabilityControl({
    super.key,
    required this.capability,
    required this.value,
    required this.enabled,
    required this.onSet,
    this.accent,
    this.onRename,
  });

  /// One entry of the descriptor's `capabilities` list.
  final Map<String, dynamic> capability;

  /// The current value from `state`, already typed by the server.
  final dynamic value;

  /// False when the device is offline, the capability is read-only, or a child
  /// has no grant for it (§5.10).
  final bool enabled;

  /// Push a new value. Returns when the server has answered, so the parent can
  /// revert on failure.
  final Future<void> Function(dynamic value) onSet;

  final Color? accent;

  /// Rename the capability (§5.11). Null hides the affordance.
  final VoidCallback? onRename;

  @override
  State<CapabilityControl> createState() => _CapabilityControlState();
}

class _CapabilityControlState extends State<CapabilityControl> {
  /// Set while a slider thumb is down, so the control follows the finger
  /// instead of snapping back to the server's value between frames.
  double? _dragging;

  String get _key => widget.capability['key'] as String;
  String get _kind => (widget.capability['kind'] ?? '') as String;
  String get _label => (widget.capability['label'] ?? _key) as String;
  String get _access => (widget.capability['access'] ?? 'rw') as String;
  bool get _readOnly => _access == 'r';
  bool get _needsConfirm => widget.capability['confirm'] == true;
  String? get _unit => widget.capability['unit'] as String?;

  double? _num(String field) {
    final raw = widget.capability[field];
    if (raw is num) return raw.toDouble();
    return null;
  }

  /// §5.4: a `confirm: true` capability needs a human's yes, and the server
  /// refuses it without one — so ask, and only then claim it was confirmed.
  Future<bool> _confirmed(String what) async {
    if (!_needsConfirm) return true;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(_label),
        content: Text(what),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Confirm')),
        ],
      ),
    );
    return ok == true;
  }

  Future<void> _push(dynamic value, {String? confirmText}) async {
    if (!await _confirmed(confirmText ?? 'Apply this change?')) return;
    await widget.onSet(value);
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;
    final accent = widget.accent ?? cs.primary;

    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
      decoration: BoxDecoration(
        color: cs.surfaceContainerHighest.withOpacity(0.5),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              _dot(cs, accent),
              const SizedBox(width: 12),
              Expanded(child: _name(cs, tt)),
              if (!widget.enabled && !_readOnly)
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: Icon(Icons.lock_outline_rounded,
                      size: 16, color: cs.onSurfaceVariant.withOpacity(0.4)),
                ),
              _trailing(cs, tt, accent),
            ],
          ),
          // A slider needs the full width, so it sits under the name rather
          // than being squeezed into the trailing slot.
          if (_kind == 'range' && !_readOnly) _slider(accent),
        ],
      ),
    );
  }

  Widget _dot(ColorScheme cs, Color accent) {
    final lit = _kind == 'switch' && widget.value == 'on';
    return Container(
      width: 10,
      height: 10,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: lit ? accent : cs.onSurfaceVariant.withOpacity(0.25),
      ),
    );
  }

  Widget _name(ColorScheme cs, TextTheme tt) {
    final text = Row(
      children: [
        Flexible(
          child: Text(_label,
              style: tt.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
              overflow: TextOverflow.ellipsis),
        ),
        if (widget.onRename != null) ...[
          const SizedBox(width: 6),
          Icon(Icons.edit_outlined,
              size: 13, color: cs.onSurfaceVariant.withOpacity(0.5)),
        ],
      ],
    );
    if (widget.onRename == null) return text;
    return GestureDetector(onTap: widget.onRename, child: text);
  }

  /// The control itself, or a readout when the capability is read-only.
  Widget _trailing(ColorScheme cs, TextTheme tt, Color accent) {
    if (_readOnly) return _readout(cs, tt);

    switch (_kind) {
      case 'switch':
        return Switch.adaptive(
          value: widget.value == 'on',
          onChanged: widget.enabled
              ? (v) => _push(v ? 'on' : 'off',
                  confirmText: v ? 'Turn $_label on?' : 'Turn $_label off?')
              : null,
          activeColor: accent,
        );

      case 'range':
        // The slider is rendered below; show the number here.
        return Text(_formatted(_dragging ?? widget.value),
            style: tt.bodyMedium?.copyWith(fontWeight: FontWeight.w700));

      case 'number':
      case 'duration':
      case 'text':
        return _editButton(cs, tt);

      case 'enum':
        return _dropdown(cs, tt);

      case 'button':
        return FilledButton.tonal(
          onPressed: widget.enabled
              ? () => _push(null, confirmText: 'Press $_label?')
              : null,
          child: const Text('Press'),
        );

      case 'color':
        return _colorChip(cs);

      case 'time':
        return TextButton(
          onPressed: widget.enabled ? _pickTime : null,
          child: Text(
              (widget.value is String && (widget.value as String).isNotEmpty)
                  ? widget.value as String
                  : '--:--',
              style: tt.bodyMedium?.copyWith(fontWeight: FontWeight.w700)),
        );

      case 'location':
        return _readout(cs, tt);

      default:
        // §11: a kind this build does not know degrades to a read-only value,
        // so a newer device still reports something useful here.
        return _readout(cs, tt);
    }
  }

  Widget _readout(ColorScheme cs, TextTheme tt) {
    final text = _formatted(widget.value);
    final min = _num('min');
    final max = _num('max');
    // §5.7: a read-only number with bounds can be a gauge, which reads at a
    // glance; without them all we can honestly show is the number.
    if (_kind == 'number' && min != null && max != null && widget.value is num) {
      final span = max - min;
      final frac = span <= 0
          ? 0.0
          : (((widget.value as num).toDouble() - min) / span).clamp(0.0, 1.0);
      return SizedBox(
        width: 120,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Text(text,
                style: tt.bodyMedium?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 4),
            ClipRRect(
              borderRadius: BorderRadius.circular(4),
              child: LinearProgressIndicator(
                value: frac,
                minHeight: 5,
                backgroundColor: cs.onSurfaceVariant.withOpacity(0.15),
              ),
            ),
          ],
        ),
      );
    }
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 160),
      child: Text(text,
          textAlign: TextAlign.right,
          style: tt.bodyMedium?.copyWith(fontWeight: FontWeight.w700),
          overflow: TextOverflow.ellipsis),
    );
  }

  Widget _slider(Color accent) {
    final min = _num('min') ?? 0;
    final max = _num('max') ?? 100;
    final step = _num('step');
    final current =
        _dragging ?? ((widget.value is num) ? (widget.value as num).toDouble() : min);
    final divisions =
        (step != null && step > 0 && max > min) ? ((max - min) / step).round() : null;
    return Slider(
      value: current.clamp(min, max),
      min: min,
      max: max,
      divisions: (divisions != null && divisions > 1) ? divisions : null,
      activeColor: accent,
      onChanged: widget.enabled ? (v) => setState(() => _dragging = v) : null,
      onChangeEnd: widget.enabled
          ? (v) async {
              // Whole numbers unless the step says otherwise — a fan speed of
              // 59.9999 is an artefact of the widget, not a user's intent.
              final value = (step != null && step % 1 != 0) ? v : v.round();
              try {
                await _push(value, confirmText: 'Set $_label to $value?');
              } finally {
                if (mounted) setState(() => _dragging = null);
              }
            }
          : null,
    );
  }

  Widget _dropdown(ColorScheme cs, TextTheme tt) {
    final options = (widget.capability['options'] as List?)
            ?.map((o) => o.toString())
            .toList() ??
        const <String>[];
    final value = options.contains(widget.value) ? widget.value as String : null;
    return DropdownButton<String>(
      value: value,
      hint: const Text('—'),
      underline: const SizedBox.shrink(),
      items: options
          .map((o) => DropdownMenuItem(value: o, child: Text(o)))
          .toList(),
      onChanged: widget.enabled
          ? (v) {
              if (v != null) _push(v, confirmText: 'Set $_label to $v?');
            }
          : null,
    );
  }

  Widget _colorChip(ColorScheme cs) {
    final hex = (widget.value is String) ? widget.value as String : '#000000';
    Color swatch;
    try {
      swatch = Color(int.parse(hex.substring(1), radix: 16) + 0xFF000000);
    } catch (_) {
      swatch = cs.onSurfaceVariant;
    }
    return GestureDetector(
      onTap: widget.enabled ? _pickColor : null,
      child: Container(
        width: 28,
        height: 28,
        decoration: BoxDecoration(
          color: swatch,
          shape: BoxShape.circle,
          border: Border.all(color: cs.outlineVariant),
        ),
      ),
    );
  }

  Widget _editButton(ColorScheme cs, TextTheme tt) {
    return TextButton(
      onPressed: widget.enabled ? _editValue : null,
      child: Text(_formatted(widget.value),
          style: tt.bodyMedium?.copyWith(fontWeight: FontWeight.w700)),
    );
  }

  // ── Editors ─────────────────────────────────────────────────────
  Future<void> _editValue() async {
    final isText = _kind == 'text';
    final ctrl = TextEditingController(
        text: widget.value == null ? '' : widget.value.toString());
    final maxChars = (_kind == 'text') ? _num('max')?.toInt() : null;
    final entered = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(_label),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          maxLength: maxChars,
          keyboardType: isText ? TextInputType.text : TextInputType.number,
          decoration: InputDecoration(
            suffixText: _unit,
            helperText: _bounds(),
          ),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, ctrl.text.trim()),
              child: const Text('Set')),
        ],
      ),
    );
    if (entered == null) return;
    if (isText) {
      await _push(entered);
      return;
    }
    final parsed = num.tryParse(entered);
    if (parsed == null) {
      _complain('That is not a number');
      return;
    }
    // The server validates against the declaration anyway; checking here just
    // saves a round trip and gives a better message.
    final min = _num('min') ?? (_kind == 'duration' ? 0 : null);
    final max = _num('max');
    if (min != null && parsed < min) {
      _complain('Must be at least ${_trim(min)}');
      return;
    }
    if (max != null && parsed > max) {
      _complain('Must be at most ${_trim(max)}');
      return;
    }
    await _push(parsed % 1 == 0 ? parsed.toInt() : parsed);
  }

  Future<void> _pickTime() async {
    final now = TimeOfDay.now();
    TimeOfDay initial = now;
    if (widget.value is String && (widget.value as String).contains(':')) {
      final parts = (widget.value as String).split(':');
      final h = int.tryParse(parts[0]);
      final m = int.tryParse(parts[1]);
      if (h != null && m != null) initial = TimeOfDay(hour: h, minute: m);
    }
    final picked = await showTimePicker(context: context, initialTime: initial);
    if (picked == null) return;
    final hh = picked.hour.toString().padLeft(2, '0');
    final mm = picked.minute.toString().padLeft(2, '0');
    await _push('$hh:$mm', confirmText: 'Set $_label to $hh:$mm?');
  }

  Future<void> _pickColor() async {
    // A full colour wheel is a dependency; a row of swatches is honest, works
    // offline and covers what a lamp is actually asked to do.
    const swatches = [
      '#ffffff', '#ffd27f', '#ff8800', '#ef4444',
      '#10b981', '#3b82f6', '#8b5cf6', '#ec4899',
    ];
    final picked = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(_label),
        content: Wrap(
          spacing: 12,
          runSpacing: 12,
          children: swatches.map((hex) {
            final c = Color(int.parse(hex.substring(1), radix: 16) + 0xFF000000);
            return GestureDetector(
              onTap: () => Navigator.pop(ctx, hex),
              child: Container(
                width: 36,
                height: 36,
                decoration: BoxDecoration(
                  color: c,
                  shape: BoxShape.circle,
                  border: Border.all(
                      color: Theme.of(ctx).colorScheme.outlineVariant),
                ),
              ),
            );
          }).toList(),
        ),
      ),
    );
    if (picked != null) await _push(picked);
  }

  void _complain(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(message),
      behavior: SnackBarBehavior.floating,
    ));
  }

  String? _bounds() {
    final min = _num('min');
    final max = _num('max');
    if (_kind == 'text' && max != null) return 'Up to ${max.toInt()} characters';
    if (min != null && max != null) return '${_trim(min)} to ${_trim(max)}';
    if (max != null) return 'At most ${_trim(max)}';
    if (min != null) return 'At least ${_trim(min)}';
    return null;
  }

  String _trim(num n) => n % 1 == 0 ? n.toInt().toString() : n.toString();

  /// A value as a person reads it, with the unit as a suffix — §5.1 is explicit
  /// that `unit` is display only and never parsed.
  String _formatted(dynamic value) {
    if (value == null) return '—';
    if (_kind == 'switch') return value == 'on' ? 'On' : 'Off';
    if (_kind == 'duration' && value is num) return _duration(value.toInt());
    if (_kind == 'location' && value is Map) {
      final lat = value['lat'];
      final lng = value['lng'];
      if (lat is num && lng is num) {
        return '${lat.toStringAsFixed(4)}, ${lng.toStringAsFixed(4)}';
      }
    }
    final text = value is num ? _trim(value) : value.toString();
    return _unit == null ? text : '$text$_unit';
  }

  String _duration(int seconds) {
    if (seconds < 60) return '${seconds}s';
    final minutes = seconds ~/ 60;
    if (minutes < 60) return '${minutes}m';
    final hours = minutes ~/ 60;
    final rest = minutes % 60;
    return rest == 0 ? '${hours}h' : '${hours}h ${rest}m';
  }
}

/// The reserved `_` keys as a strip of device chrome (§5.3).
///
/// They are facts about the device rather than controls, so they belong in the
/// card header and not in the list a person scrolls looking for the lamp.
/// `_report_every` is the exception — it is a setting, so the card renders it as
/// an ordinary control.
class CapabilityChrome extends StatelessWidget {
  const CapabilityChrome({
    super.key,
    required this.capabilities,
    required this.state,
  });

  final List<Map<String, dynamic>> capabilities;
  final Map<String, dynamic> state;

  static const _icons = {
    '_batt': Icons.battery_std_rounded,
    '_rssi': Icons.wifi_rounded,
    '_fw': Icons.memory_rounded,
    '_uptime': Icons.schedule_rounded,
  };

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;
    final chips = <Widget>[];

    for (final cap in capabilities) {
      final key = cap['key'] as String;
      if (!_icons.containsKey(key)) continue;
      final value = state[key];
      if (value == null) continue;
      final unit = cap['unit'] as String?;
      final text = key == '_uptime' && value is num
          ? _uptime(value.toInt())
          : '${value is num ? (value % 1 == 0 ? value.toInt() : value) : value}'
              '${unit ?? ''}';
      chips.add(Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(_icons[key], size: 13, color: cs.onSurfaceVariant),
          const SizedBox(width: 4),
          Text(text,
              style: tt.labelSmall?.copyWith(color: cs.onSurfaceVariant)),
        ],
      ));
    }

    if (chips.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 6, bottom: 2),
      child: Wrap(spacing: 14, runSpacing: 4, children: chips),
    );
  }

  static String _uptime(int seconds) {
    final days = seconds ~/ 86400;
    if (days > 0) return '${days}d';
    final hours = seconds ~/ 3600;
    if (hours > 0) return '${hours}h';
    return '${seconds ~/ 60}m';
  }
}
