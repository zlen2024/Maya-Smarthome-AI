import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:shared_preferences/shared_preferences.dart';

const String SERVICE_UUID = "12345678-1234-1234-1234-123456789000";
const String SSID_UUID = "12345678-1234-1234-1234-123456789001";
const String PASS_UUID = "12345678-1234-1234-1234-123456789002";
const String WSURL_UUID = "12345678-1234-1234-1234-123456789004";
const String PIN_UUID = "12345678-1234-1234-1234-123456789003";

class ProvisionScreen extends StatefulWidget {
  const ProvisionScreen({super.key});

  @override
  State<ProvisionScreen> createState() => _ProvisionScreenState();
}

class _ProvisionScreenState extends State<ProvisionScreen> {
  final TextEditingController _ssidController = TextEditingController();
  final TextEditingController _passController = TextEditingController();
  final TextEditingController _urlController = TextEditingController();
  final TextEditingController _pinController = TextEditingController(
    text: "0000",
  );

  BluetoothDevice? _connectedDevice;
  bool _isScanning = false;
  String _statusLog = "Ready to scan.";

  BluetoothCharacteristic? _ssidChar;
  BluetoothCharacteristic? _passChar;
  BluetoothCharacteristic? _urlChar;
  BluetoothCharacteristic? _pinChar;

  StreamSubscription<List<ScanResult>>? _scanSubscription;

  @override
  void initState() {
    super.initState();
    _checkPermissions();
  }

  @override
  void dispose() {
    _scanSubscription?.cancel();
    if (_connectedDevice != null) {
      _connectedDevice!.disconnect();
    }
    super.dispose();
  }

  Future<void> _checkPermissions() async {
    await [
      Permission.bluetoothScan,
      Permission.bluetoothConnect,
      Permission.location,
    ].request();
  }

  void _startScan() async {
    setState(() {
      _isScanning = true;
      _statusLog = "Scanning for 'MyIoT-Setup'...";
    });

    _scanSubscription = FlutterBluePlus.onScanResults.listen((results) {
      for (ScanResult r in results) {
        if (r.device.platformName == "MyIoT-Setup") {
          _connectToDevice(r.device);
          FlutterBluePlus.stopScan();
          break;
        }
      }
    }, onError: (e) => print(e));

    await FlutterBluePlus.startScan(timeout: const Duration(seconds: 10));

    await Future.delayed(const Duration(seconds: 10));
    if (_connectedDevice == null && mounted) {
      setState(() {
        _isScanning = false;
        if (_statusLog.contains("Scanning"))
          _statusLog = "Device not found. Try again.";
      });
    }
  }

  Future<void> _connectToDevice(BluetoothDevice device) async {
    setState(() => _statusLog = "Found! Connecting...");

    try {
      await device.connect();
      setState(() {
        _connectedDevice = device;
        _statusLog = "Connected! Discovering Services...";
      });

      List<BluetoothService> services = await device.discoverServices();

      for (var service in services) {
        if (service.uuid == Guid(SERVICE_UUID)) {
          for (var c in service.characteristics) {
            if (c.uuid == Guid(SSID_UUID)) _ssidChar = c;
            if (c.uuid == Guid(PASS_UUID)) _passChar = c;
            if (c.uuid == Guid(WSURL_UUID)) _urlChar = c;
            if (c.uuid == Guid(PIN_UUID)) _pinChar = c;
          }
        }
      }

      if (_ssidChar != null &&
          _passChar != null &&
          _urlChar != null &&
          _pinChar != null) {
        setState(() => _statusLog = "Ready to Provision!");
      } else {
        setState(() => _statusLog =
            "Error: Missing characteristics - SSID:${_ssidChar != null} PASS:${_passChar != null} URL:${_urlChar != null} PIN:${_pinChar != null}");
        await device.disconnect();
      }
    } catch (e) {
      setState(() => _statusLog = "Connection failed: $e");
    }
  }

  Future<void> _provisionDevice() async {
    if (_connectedDevice == null) return;

    setState(() => _statusLog = "Sending data...");

    try {
      if (_ssidChar != null) {
        await _ssidChar!.write(utf8.encode(_ssidController.text));
        setState(() => _statusLog = "Sent SSID...");
        await Future.delayed(const Duration(milliseconds: 200));
      }

      if (_passChar != null) {
        await _passChar!.write(utf8.encode(_passController.text));
        setState(() => _statusLog = "Sent PASS...");
        await Future.delayed(const Duration(milliseconds: 200));
      }

      if (_urlChar != null) {
        await _urlChar!.write(utf8.encode(_urlController.text));
        setState(() => _statusLog = "Sent URL...");
        await Future.delayed(const Duration(milliseconds: 200));
      }

      if (_pinChar != null) {
        await _pinChar!.write(utf8.encode(_pinController.text));
        setState(() => _statusLog = "Sent PIN! Waiting for ESP32...");
      }

      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('ws_url', _urlController.text);
      await prefs.setString('device_pin', _pinController.text);
      await prefs.setString('device_id', 'esp32-9f83b1c1');

      setState(() => _statusLog = "Provisioned! Settings saved.");
    } catch (e) {
      setState(() => _statusLog = "Write failed: $e");
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text("BLE Provisioning")),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20.0),
        child: Column(
          children: [
            Container(
              padding: const EdgeInsets.all(10),
              color: Colors.grey[200],
              width: double.infinity,
              child: Text(
                _statusLog,
                style: const TextStyle(fontWeight: FontWeight.bold),
              ),
            ),
            const SizedBox(height: 20),
            if (_connectedDevice == null)
              ElevatedButton.icon(
                icon: _isScanning
                    ? const SizedBox(
                        width: 12,
                        height: 12,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.bluetooth_searching),
                label: Text(_isScanning ? "Scanning..." : "Scan for ESP32"),
                onPressed: _isScanning ? null : _startScan,
              ),
            if (_connectedDevice != null) ...[
              const SizedBox(height: 20),
              TextField(
                controller: _ssidController,
                decoration: const InputDecoration(labelText: "WiFi SSID"),
              ),
              TextField(
                controller: _passController,
                decoration: const InputDecoration(labelText: "WiFi Password"),
              ),
              TextField(
                controller: _urlController,
                decoration: const InputDecoration(
                  labelText: "WebSocket URL (ws://...)",
                ),
              ),
              TextField(
                controller: _pinController,
                decoration: const InputDecoration(labelText: "Security PIN"),
              ),
              const SizedBox(height: 30),
              SizedBox(
                width: double.infinity,
                height: 50,
                child: ElevatedButton(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.blue,
                    foregroundColor: Colors.white,
                  ),
                  onPressed: _provisionDevice,
                  child: const Text("PROVISION DEVICE"),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
