import 'package:flutter/material.dart';
import '../services/api_service.dart';

/// Device marketplace with a mock checkout — orders are recorded server-side
/// but no real payment is taken.
class StoreScreen extends StatefulWidget {
  const StoreScreen({super.key});

  @override
  State<StoreScreen> createState() => _StoreScreenState();
}

class _StoreScreenState extends State<StoreScreen> {
  List<dynamic> _catalog = [];
  List<dynamic> _orders = [];
  bool _loading = true;
  bool _buying = false;

  @override
  void initState() {
    super.initState();
    _fetch();
  }

  Future<void> _fetch() async {
    try {
      final results = await Future.wait([
        ApiService.getStoreCatalog(),
        ApiService.getOrders(),
      ]);
      if (mounted) {
        setState(() {
          _catalog = results[0];
          _orders = results[1];
          _loading = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _buy(dynamic item) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Buy ${item['name']}?'),
        content: Text(
            'RM ${(item['price'] as num).toStringAsFixed(2)}\n\n'
            'This is a demo checkout — no real payment will be taken. '
            'The order is recorded to your house account.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Confirm purchase'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    setState(() => _buying = true);
    try {
      final order = await ApiService.placeOrder(item['sku']);
      _snack('Order #${order['order_id']} confirmed — ${order['item_name']}');
      _fetch();
    } catch (e) {
      _snack(e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _buying = false);
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

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;

    return Scaffold(
      appBar: AppBar(title: const Text('Maya Store')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _fetch,
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  ..._catalog.map((item) => Card(
                        margin: const EdgeInsets.only(bottom: 12),
                        color: cs.surfaceContainerLow,
                        child: Padding(
                          padding: const EdgeInsets.all(16),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Icon(Icons.power_rounded,
                                      color: cs.primary, size: 32),
                                  const SizedBox(width: 12),
                                  Expanded(
                                    child: Text(item['name'] ?? '',
                                        style: tt.titleMedium?.copyWith(
                                            fontWeight: FontWeight.w700)),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 8),
                              Text(item['description'] ?? '',
                                  style: tt.bodySmall?.copyWith(
                                      color: cs.onSurfaceVariant)),
                              const SizedBox(height: 12),
                              Row(
                                mainAxisAlignment:
                                    MainAxisAlignment.spaceBetween,
                                children: [
                                  Text(
                                      'RM ${(item['price'] as num).toStringAsFixed(2)}',
                                      style: tt.titleMedium?.copyWith(
                                          fontWeight: FontWeight.w800,
                                          color: cs.primary)),
                                  FilledButton.icon(
                                    onPressed:
                                        _buying ? null : () => _buy(item),
                                    icon: const Icon(
                                        Icons.shopping_cart_outlined,
                                        size: 18),
                                    label: const Text('Buy'),
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                      )),
                  if (_orders.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Text('Order history',
                        style: tt.titleSmall
                            ?.copyWith(fontWeight: FontWeight.w700)),
                    const SizedBox(height: 8),
                    ..._orders.map((o) => ListTile(
                          dense: true,
                          leading: const Icon(Icons.receipt_long_outlined),
                          title: Text(o['item_name'] ?? ''),
                          subtitle: Text(
                              '#${o['order_id']} · ${o['status']} · ${(o['created_at'] ?? '').toString().split('T').first}'),
                          trailing: Text(
                              'RM ${(o['price'] as num).toStringAsFixed(2)}'),
                        )),
                  ],
                ],
              ),
            ),
    );
  }
}
