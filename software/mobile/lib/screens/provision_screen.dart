import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:permission_handler/permission_handler.dart';
import '../services/api_service.dart';

// BLE Characteristic UUIDs (must match ESP32 firmware)
const SERVICE_UUID = "12345678-1234-1234-1234-123456789000";
const SSID_UUID = "12345678-1234-1234-1234-123456789001";
const PASS_UUID = "12345678-1234-1234-1234-123456789002";
const PIN_UUID = "12345678-1234-1234-1234-123456789003";
const WSURL_UUID = "12345678-1234-1234-1234-123456789004";

/// BLE provisioning screen — scans for "Maya-Setup" ESP32 devices and
/// writes WiFi credentials + server WebSocket URL over BLE characteristics.
class ProvisionScreen extends StatefulWidget {
  const ProvisionScreen({super.key});

  @override
  State<ProvisionScreen> createState() => _ProvisionScreenState();
}

class _ProvisionScreenState extends State<ProvisionScreen> {
  final _ssidCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  final _pinCtrl = TextEditingController(text: '0000');

  // Pre-fill WS URL with production server
  late final TextEditingController _urlCtrl =
      TextEditingController(text: '${ApiService.wsUrl}/ws/device');

  BluetoothDevice? _connectedDevice;
  bool _isScanning = false;
  String _statusLog = 'Ready to scan for devices.';
  bool _provisioning = false;

  BluetoothCharacteristic? _ssidChar;
  BluetoothCharacteristic? _passChar;
  BluetoothCharacteristic? _urlChar;
  BluetoothCharacteristic? _pinChar;

  StreamSubscription? _scanSub;

  @override
  void initState() {
    super.initState();
    _requestPermissions();
  }

  @override
  void dispose() {
    _scanSub?.cancel();
    _ssidCtrl.dispose();
    _passCtrl.dispose();
    _urlCtrl.dispose();
    _pinCtrl.dispose();
    _connectedDevice?.disconnect();
    super.dispose();
  }

  // ── Permissions ────────────────────────────────────────────────
  Future<void> _requestPermissions() async {
    if (Platform.isAndroid) {
      await [
        Permission.bluetoothScan,
        Permission.bluetoothConnect,
        Permission.location,
      ].request();
    }
  }

  // ── BLE Scan ───────────────────────────────────────────────────
  Future<void> _startScan() async {
    setState(() {
      _isScanning = true;
      _statusLog = 'Scanning for "Maya-Setup" BLE device...';
    });

    await FlutterBluePlus.startScan(timeout: const Duration(seconds: 15));

    _scanSub = FlutterBluePlus.scanResults.listen((results) async {
      for (final r in results) {
        if (r.device.platformName == 'Maya-Setup') {
          await FlutterBluePlus.stopScan();
          _scanSub?.cancel();
          setState(() {
            _statusLog = 'Found Maya-Setup! Connecting...';
          });
          _connectDevice(r.device);
          return;
        }
      }
    });

    // Handle scan timeout
    await Future.delayed(const Duration(seconds: 16));
    if (_connectedDevice == null && mounted) {
      setState(() {
        _isScanning = false;
        _statusLog = 'Scan complete. "Maya-Setup" not found. Try again.';
      });
    }
  }

  // ── BLE Connect ────────────────────────────────────────────────
  Future<void> _connectDevice(BluetoothDevice device) async {
    try {
      await device.connect(timeout: const Duration(seconds: 10));

      if (Platform.isAndroid) {
        await device.requestMtu(512);
      }

      final services = await device.discoverServices();

      // Find our custom service
      for (final svc in services) {
        if (svc.uuid.toString().toLowerCase() ==
            SERVICE_UUID.toLowerCase()) {
          for (final ch in svc.characteristics) {
            final uuid = ch.uuid.toString().toLowerCase();
            if (uuid == SSID_UUID.toLowerCase()) _ssidChar = ch;
            if (uuid == PASS_UUID.toLowerCase()) _passChar = ch;
            if (uuid == WSURL_UUID.toLowerCase()) _urlChar = ch;
            if (uuid == PIN_UUID.toLowerCase()) _pinChar = ch;
          }
        }
      }

      if (_ssidChar == null ||
          _passChar == null ||
          _urlChar == null ||
          _pinChar == null) {
        setState(() {
          _statusLog =
              'Connected but missing BLE characteristics. Check firmware.';
          _isScanning = false;
        });
        return;
      }

      setState(() {
        _connectedDevice = device;
        _isScanning = false;
        _statusLog =
            'Connected to Maya-Setup! Fill in the details and provision.';
      });
    } catch (e) {
      setState(() {
        _isScanning = false;
        _statusLog = 'Connection failed: $e';
      });
    }
  }

  // ── BLE Provision ──────────────────────────────────────────────
  Future<void> _provisionDevice() async {
    final ssid = _ssidCtrl.text.trim();
    final pass = _passCtrl.text.trim();
    final url = _urlCtrl.text.trim();
    final pin = _pinCtrl.text.trim();

    if (ssid.isEmpty || pass.isEmpty || url.isEmpty || pin.isEmpty) {
      _snack('Please fill in all fields');
      return;
    }

    setState(() {
      _provisioning = true;
      _statusLog = 'Writing WiFi SSID...';
    });

    try {
      await _ssidChar!.write(utf8.encode(ssid), withoutResponse: false);
      await Future.delayed(const Duration(milliseconds: 200));

      setState(() => _statusLog = 'Writing WiFi password...');
      await _passChar!.write(utf8.encode(pass), withoutResponse: false);
      await Future.delayed(const Duration(milliseconds: 200));

      setState(() => _statusLog = 'Writing server WebSocket URL...');
      await _urlChar!.write(utf8.encode(url), withoutResponse: false);
      await Future.delayed(const Duration(milliseconds: 200));

      setState(() => _statusLog = 'Writing device PIN...');
      await _pinChar!.write(utf8.encode(pin), withoutResponse: false);

      setState(() {
        _statusLog =
            '✅ Provisioning complete! The device will now connect to WiFi and the server.';
        _provisioning = false;
      });

      _snack('Provisioning successful! Register the device on the Device tab.');
    } catch (e) {
      setState(() {
        _statusLog = '❌ Provisioning failed: $e';
        _provisioning = false;
      });
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
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('BLE Provisioning'),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Status card
            Card(
              color: cs.surfaceContainerLow,
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  children: [
                    Icon(
                      _connectedDevice != null
                          ? Icons.bluetooth_connected_rounded
                          : Icons.bluetooth_searching_rounded,
                      color: _connectedDevice != null
                          ? Colors.green
                          : cs.primary,
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        _statusLog,
                        style: tt.bodySmall?.copyWith(
                            color: cs.onSurfaceVariant),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),

            // Scan button (shown when not connected)
            if (_connectedDevice == null) ...[
              FilledButton.icon(
                onPressed: _isScanning ? null : _startScan,
                icon: _isScanning
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(
                            strokeWidth: 2.5, color: Colors.white),
                      )
                    : const Icon(Icons.bluetooth_searching_rounded),
                label: Text(_isScanning
                    ? 'Scanning...'
                    : 'Scan for Maya-Setup'),
              ),
            ],

            // Config form (shown when connected)
            if (_connectedDevice != null) ...[
              TextField(
                controller: _ssidCtrl,
                decoration: const InputDecoration(
                  labelText: 'WiFi SSID',
                  prefixIcon: Icon(Icons.wifi_rounded),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _passCtrl,
                obscureText: true,
                decoration: const InputDecoration(
                  labelText: 'WiFi Password',
                  prefixIcon: Icon(Icons.lock_outline_rounded),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _urlCtrl,
                decoration: const InputDecoration(
                  labelText: 'WebSocket URL',
                  prefixIcon: Icon(Icons.link_rounded),
                  helperText: 'Auto-filled with production server',
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _pinCtrl,
                maxLength: 4,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'Device PIN',
                  prefixIcon: Icon(Icons.pin_outlined),
                  counterText: '',
                ),
              ),
              const SizedBox(height: 20),
              FilledButton.icon(
                onPressed: _provisioning ? null : _provisionDevice,
                icon: _provisioning
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(
                            strokeWidth: 2.5, color: Colors.white),
                      )
                    : const Icon(Icons.send_rounded),
                label: Text(_provisioning
                    ? 'Provisioning...'
                    : 'Provision Device'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
