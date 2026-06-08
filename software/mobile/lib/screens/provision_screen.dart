// ignore_for_file: constant_identifier_names
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
const STATUS_UUID = "12345678-1234-1234-1234-123456789006";

class ProvisionScreen extends StatefulWidget {
  const ProvisionScreen({super.key});

  @override
  State<ProvisionScreen> createState() => _ProvisionScreenState();
}

class _ProvisionScreenState extends State<ProvisionScreen> {
  // Bluetooth Adapter & Scanning States
  bool _bluetoothSupported = true;
  BluetoothAdapterState _adapterState = BluetoothAdapterState.unknown;
  bool _isScanning = false;
  List<ScanResult> _scanResults = [];
  StreamSubscription? _adapterStateSub;
  StreamSubscription? _scanResultsSub;

  // Device Connection States
  BluetoothDevice? _connectedDevice;
  bool _connecting = false;
  String? _deviceId;

  // Form Controllers
  final _nameCtrl = TextEditingController();
  final _ssidCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  final _pinCtrl = TextEditingController(text: '0000');

  // Characteristic References
  BluetoothCharacteristic? _ssidChar;
  BluetoothCharacteristic? _passChar;
  BluetoothCharacteristic? _urlChar;
  BluetoothCharacteristic? _pinChar;
  BluetoothCharacteristic? _statusChar;

  // Progress/Feedback Loop States
  bool _submitting = false;
  String _currentStep = 'idle'; // 'idle', 'registering', 'writing', 'connecting_wifi', 'connecting_ws', 'success', 'failed'
  String _statusMsg = '';
  StreamSubscription? _statusNotificationSub;

  @override
  void initState() {
    super.initState();
    _checkBluetoothSupport();
  }

  @override
  void dispose() {
    _adapterStateSub?.cancel();
    _scanResultsSub?.cancel();
    _statusNotificationSub?.cancel();
    _nameCtrl.dispose();
    _ssidCtrl.dispose();
    _passCtrl.dispose();
    _pinCtrl.dispose();
    _disconnectDevice();
    super.dispose();
  }

  // ── Bluetooth Check & Setup ─────────────────────────────────────
  Future<void> _checkBluetoothSupport() async {
    final supported = await FlutterBluePlus.isSupported;
    if (!mounted) return;
    setState(() {
      _bluetoothSupported = supported;
    });

    if (supported) {
      _adapterStateSub = FlutterBluePlus.adapterState.listen((state) {
        if (mounted) {
          setState(() {
            _adapterState = state;
          });
          if (state == BluetoothAdapterState.on) {
            _startScan();
          }
        }
      });
    }
  }

  Future<void> _enableBluetooth() async {
    if (Platform.isAndroid) {
      try {
        await FlutterBluePlus.turnOn();
      } catch (_) {}
    }
  }

  // ── Scans for nearby Maya Smart Home devices ─────────────────────
  Future<void> _startScan() async {
    if (_adapterState != BluetoothAdapterState.on) return;

    if (Platform.isAndroid) {
      await [
        Permission.bluetoothScan,
        Permission.bluetoothConnect,
        Permission.location,
      ].request();
    }

    setState(() {
      _isScanning = true;
      _scanResults.clear();
      _connectedDevice = null;
      _deviceId = null;
    });

    _scanResultsSub = FlutterBluePlus.scanResults.listen((results) {
      if (!mounted) return;
      // Filter for devices with name starting with "Maya-"
      final mayaDevices = results.where((r) {
        final name = r.advertisementData.advName;
        return name.startsWith('Maya-');
      }).toList();

      setState(() {
        _scanResults = mayaDevices;
      });
    });

    try {
      await FlutterBluePlus.startScan(timeout: const Duration(seconds: 10));
    } catch (_) {}

    await Future.delayed(const Duration(seconds: 10));
    if (mounted) {
      setState(() {
        _isScanning = false;
      });
    }
  }

  // ── Connect & Discover Services ─────────────────────────────────
  Future<void> _connectDevice(BluetoothDevice device) async {
    setState(() {
      _connecting = true;
      _connectedDevice = device;
    });

    try {
      await device.connect(timeout: const Duration(seconds: 8));
      if (Platform.isAndroid) {
        await device.requestMtu(512);
      }

      final services = await device.discoverServices();
      BluetoothService? mayaService;
      for (final s in services) {
        if (s.uuid.toString().toLowerCase() == SERVICE_UUID.toLowerCase()) {
          mayaService = s;
          break;
        }
      }

      if (mayaService == null) {
        throw Exception('Device is missing the Maya configuration service.');
      }

      // Extract characteristics
      for (final c in mayaService.characteristics) {
        final uuid = c.uuid.toString().toLowerCase();
        if (uuid == SSID_UUID.toLowerCase()) _ssidChar = c;
        if (uuid == PASS_UUID.toLowerCase()) _passChar = c;
        if (uuid == WSURL_UUID.toLowerCase()) _urlChar = c;
        if (uuid == PIN_UUID.toLowerCase()) _pinChar = c;
        if (uuid == STATUS_UUID.toLowerCase()) _statusChar = c;
      }

      if (_ssidChar == null || _passChar == null || _urlChar == null || _pinChar == null) {
        throw Exception('BLE characteristics missing. Old firmware?');
      }

      // Auto-extract device ID from name
      final name = device.platformName; // e.g. Maya-esp32-9f83b1c1
      String id = 'esp32-9f83b1c1'; // Default fallback
      if (name.startsWith('Maya-') && name != 'Maya-Setup') {
        id = name.substring(5);
      }
      _deviceId = id;

      setState(() {
        _connecting = false;
        _nameCtrl.text = 'Smart Socket ${_deviceId!.split('-').last.toUpperCase()}';
      });
    } catch (e) {
      setState(() {
        _connecting = false;
        _connectedDevice = null;
        _deviceId = null;
      });
      _showSnack(e.toString().replaceFirst('Exception: ', ''));
    }
  }

  Future<void> _disconnectDevice() async {
    _statusNotificationSub?.cancel();
    await _connectedDevice?.disconnect();
    if (mounted) {
      setState(() {
        _connectedDevice = null;
        _deviceId = null;
        _ssidChar = null;
        _passChar = null;
        _urlChar = null;
        _pinChar = null;
        _statusChar = null;
      });
    }
  }

  // ── Unified Registration & Provision Flow ───────────────────────
  Future<void> _submitRegistration() async {
    final name = _nameCtrl.text.trim();
    final ssid = _ssidCtrl.text.trim();
    final pass = _passCtrl.text.trim();
    final pin = _pinCtrl.text.trim();
    final deviceId = _deviceId;

    if (name.isEmpty || ssid.isEmpty || pass.isEmpty || pin.isEmpty || deviceId == null) {
      _showSnack('Please fill in all fields');
      return;
    }

    setState(() {
      _submitting = true;
      if (_statusChar == null) {
        _currentStep = 'registering';
        _statusMsg = 'Registering device with server...';
      } else {
        _currentStep = 'writing';
        _statusMsg = 'Writing credentials over Bluetooth...';
      }
    });

    try {
      if (_statusChar == null) {
        // For older firmware, register first to authorize polling status
        await ApiService.registerDevice(deviceId, name);
      }

      // ─── Set up notifications BEFORE writing to prevent race conditions ───
      if (_statusChar != null) {
        _statusNotificationSub = _statusChar!.onValueReceived.listen((value) {
          if (!mounted) return;
          final code = utf8.decode(value);
          _handleBleStatusCode(code, deviceId, name);
        }, onError: (e) {
          _handleFailure('BLE notification error: $e');
        });

        _connectedDevice?.cancelWhenDisconnected(_statusNotificationSub!);
        await _statusChar!.setNotifyValue(true);
        // Wait briefly for setup to register
        await Future.delayed(const Duration(milliseconds: 150));
      }

      if (_statusChar == null) {
        setState(() {
          _currentStep = 'writing';
          _statusMsg = 'Writing credentials over Bluetooth...';
        });
      }

      // 2. Write Credentials over BLE
      // Server WebSocket URL: dynamically derived from base API Url (replaces /ws/device)
      const wsTargetUrl = '${ApiService.wsUrl}/ws';

      await _ssidChar!.write(utf8.encode(ssid), withoutResponse: false);
      await Future.delayed(const Duration(milliseconds: 150));

      await _passChar!.write(utf8.encode(pass), withoutResponse: false);
      await Future.delayed(const Duration(milliseconds: 150));

      await _urlChar!.write(utf8.encode(wsTargetUrl), withoutResponse: false);
      await Future.delayed(const Duration(milliseconds: 150));

      await _pinChar!.write(utf8.encode(pin), withoutResponse: false);
      await Future.delayed(const Duration(milliseconds: 150));

      // 3. Start Connection Feedback Loop
      if (_statusChar != null) {
        setState(() {
          _currentStep = 'connecting_wifi';
          _statusMsg = 'Validating PIN and connecting to Wi-Fi...';
        });
      } else {
        // Fallback for older firmware: Poll the server API for device status
        setState(() {
          _currentStep = 'connecting_ws';
          _statusMsg = 'Connecting to server (polling status)...';
        });
        _startServerPollingFallback(deviceId);
      }

    } catch (e) {
      if (_statusChar == null) {
        // Clean up registration on failure for older firmware
        try {
          await ApiService.deleteDevice(deviceId);
        } catch (_) {}
      }
      _handleFailure(e.toString().replaceFirst('Exception: ', ''));
    }
  }

  Future<void> _registerDeviceOnSuccessAndComplete(String deviceId, String name) async {
    setState(() {
      _currentStep = 'registering';
      _statusMsg = 'Registering device with your account...';
    });
    try {
      await ApiService.registerDevice(deviceId, name);
      _handleSuccess();
    } catch (e) {
      _handleFailure('WiFi connected successfully, but server registration failed: $e');
    }
  }

  void _handleBleStatusCode(String code, String deviceId, String name) {
    switch (code) {
      case '1':
        setState(() {
          _currentStep = 'connecting_wifi';
          _statusMsg = 'PIN accepted. Connecting device to Wi-Fi...';
        });
        break;
      case '2':
        setState(() {
          _currentStep = 'connecting_ws';
          _statusMsg = 'Wi-Fi connected. Establishing WebSocket connection...';
        });
        break;
      case '3':
        _registerDeviceOnSuccessAndComplete(deviceId, name);
        break;
      case '4':
        _handleFailure('Wi-Fi connection failed. Double-check SSID and password.');
        break;
      case '5':
        _handleFailure('Server WebSocket connection failed. Verify server URL/status.');
        break;
      case '6':
        _handleFailure('Incorrect Security PIN. Device rejected credentials.');
        break;
      case '7':
        _handleFailure('Failed to connect to new Wi-Fi. Reverted to previous connection successfully.');
        break;
      default:
        // Ignore other codes
        break;
    }
  }

  Future<void> _cleanupAndFail(String deviceId, String error) async {
    setState(() {
      _statusMsg = 'Setup failed. Cleaning up registration...';
    });
    try {
      await ApiService.deleteDevice(deviceId);
    } catch (_) {}
    _handleFailure(error);
  }

  void _startServerPollingFallback(String deviceId) async {
    int attempts = 0;
    String? initialHeartbeat;
    try {
      final initialDev = await ApiService.getDevice(deviceId);
      initialHeartbeat = initialDev['last_heartbeat'];
    } catch (_) {}

    Timer.periodic(const Duration(seconds: 2), (timer) async {
      attempts++;
      if (!_submitting || !mounted) {
        timer.cancel();
        return;
      }

      try {
        final dev = await ApiService.getDevice(deviceId);
        final newHeartbeat = dev['last_heartbeat'];
        // Ensure the device is online and the heartbeat timestamp has updated since we started
        if (dev['online'] == true && newHeartbeat != initialHeartbeat) {
          timer.cancel();
          _handleSuccess();
          return;
        }
      } catch (_) {}

      if (attempts >= 10) { // 20 seconds timeout
        timer.cancel();
        _cleanupAndFail(deviceId, 'Server polling timed out. Device failed to connect online.');
      }
    });
  }

  void _handleSuccess({bool isWarning = false}) {
    setState(() {
      _currentStep = 'success';
      _statusMsg = isWarning
          ? 'Provisioning complete. Status verification timed out.'
          : 'Device successfully registered and connected!';
    });

    _showSnack(isWarning
        ? 'Credentials sent! Please verify connection on the dashboard.'
        : 'Device registered successfully!');

    Future.delayed(const Duration(milliseconds: 2500), () {
      if (mounted) {
        Navigator.pop(context, true);
      }
    });
  }

  void _handleFailure(String error) {
    setState(() {
      _submitting = false;
      _currentStep = 'failed';
      _statusMsg = error;
    });

    _statusNotificationSub?.cancel();
    _showSnack(error);
  }

  void _showSnack(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..clearSnackBars()
      ..showSnackBar(SnackBar(
        content: Text(msg),
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ));
  }

  // ── UI Render Methods ───────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Register Device'),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: _submitting ? null : () => Navigator.pop(context),
        ),
      ),
      body: _submitting
          ? _buildProgressOverlay(cs, tt)
          : SingleChildScrollView(
              padding: const EdgeInsets.all(20),
              child: _buildMainContent(cs, tt),
            ),
    );
  }

  Widget _buildMainContent(ColorScheme cs, TextTheme tt) {
    if (!_bluetoothSupported) {
      return _buildErrorState(
        Icons.bluetooth_disabled_rounded,
        'Bluetooth Not Supported',
        'This device does not support Bluetooth Low Energy, which is required for setup.',
        cs,
        tt,
      );
    }

    if (_adapterState != BluetoothAdapterState.on) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const SizedBox(height: 40),
          _buildErrorState(
            Icons.bluetooth_disabled_rounded,
            'Bluetooth is Disabled',
            'Please enable Bluetooth to scan and register nearby Maya Smart Home devices.',
            cs,
            tt,
          ),
          const SizedBox(height: 24),
          if (Platform.isAndroid)
            FilledButton.icon(
              onPressed: _enableBluetooth,
              icon: const Icon(Icons.bluetooth_rounded),
              label: const Text('Enable Bluetooth'),
            ),
        ],
      );
    }

    if (_connectedDevice == null) {
      return _buildDiscoveryList(cs, tt);
    }

    return _buildConfigForm(cs, tt);
  }

  Widget _buildErrorState(
      IconData icon, String title, String subtitle, ColorScheme cs, TextTheme tt) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          children: [
            Icon(icon, size: 64, color: cs.error),
            const SizedBox(height: 16),
            Text(title, style: tt.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            Text(subtitle, style: tt.bodyMedium?.copyWith(color: cs.onSurfaceVariant), textAlign: TextAlign.center),
          ],
        ),
      ),
    );
  }

  // ── Scanned Devices List ────────────────────────────────────────
  Widget _buildDiscoveryList(ColorScheme cs, TextTheme tt) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // Scan status card
        Card(
          color: cs.surfaceContainerLow,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                if (_isScanning)
                  const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                else
                  Icon(Icons.bluetooth_searching_rounded, color: cs.primary),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    _isScanning
                        ? 'Searching for Maya Smart Home devices...'
                        : 'Search complete. Select a device to connect.',
                    style: tt.bodySmall?.copyWith(color: cs.onSurfaceVariant),
                  ),
                ),
                if (!_isScanning)
                  IconButton(
                    icon: const Icon(Icons.refresh),
                    onPressed: _startScan,
                  ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 20),

        Text(
          'Nearby Devices',
          style: tt.titleSmall?.copyWith(fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 8),

        if (_scanResults.isEmpty)
          Card(
            color: cs.surfaceContainerLow,
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 48, horizontal: 16),
              child: Column(
                children: [
                  Icon(Icons.sensors_off_rounded, size: 48, color: cs.onSurfaceVariant.withOpacity(0.3)),
                  const SizedBox(height: 12),
                  Text('No devices found', style: tt.bodyMedium?.copyWith(color: cs.onSurfaceVariant)),
                  const SizedBox(height: 4),
                  Text(
                    'Ensure your Smart Socket is in BLE setup mode.',
                    style: tt.bodySmall?.copyWith(color: cs.onSurfaceVariant),
                    textAlign: TextAlign.center,
                  ),
                ],
              ),
            ),
          )
        else
          ..._scanResults.map((r) {
            final name = r.advertisementData.advName;
            return Card(
              margin: const EdgeInsets.only(bottom: 8),
              color: cs.surfaceContainerLow,
              child: ListTile(
                leading: CircleAvatar(
                  backgroundColor: cs.primary.withOpacity(0.1),
                  child: Icon(Icons.settings_remote_rounded, color: cs.primary, size: 20),
                ),
                title: Text(
                  name == 'Maya-Setup' ? 'Maya Smart Socket (Setup Mode)' : name,
                  style: tt.bodyMedium?.copyWith(fontWeight: FontWeight.bold),
                ),
                subtitle: Text(
                  r.device.remoteId.str,
                  style: const TextStyle(fontFamily: 'monospace', fontSize: 11),
                ),
                trailing: _connecting && _connectedDevice == r.device
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2.5),
                      )
                    : Icon(Icons.arrow_forward_ios_rounded, size: 16, color: cs.onSurfaceVariant),
                onTap: _connecting ? null : () => _connectDevice(r.device),
              ),
            );
          }),
      ],
    );
  }

  // ── Registration Config Form ────────────────────────────────────
  Widget _buildConfigForm(ColorScheme cs, TextTheme tt) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // Connected info header
        Row(
          children: [
            const Icon(Icons.check_circle_rounded, color: Colors.green, size: 20),
            const SizedBox(width: 8),
            Text(
              'Connected to Maya BLE setup',
              style: tt.bodyMedium?.copyWith(color: Colors.green, fontWeight: FontWeight.bold),
            ),
            const Spacer(),
            TextButton.icon(
              onPressed: _disconnectDevice,
              icon: const Icon(Icons.close, size: 16),
              label: const Text('Disconnect'),
            ),
          ],
        ),
        const SizedBox(height: 12),

        Card(
          color: cs.surfaceContainerLow,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            child: Row(
              children: [
                Icon(Icons.qr_code_rounded, color: cs.primary, size: 24),
                const SizedBox(width: 12),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Detected Device ID', style: tt.labelSmall?.copyWith(color: cs.onSurfaceVariant)),
                    Text(
                      _deviceId ?? 'Loading...',
                      style: tt.bodyMedium?.copyWith(
                        fontFamily: 'monospace',
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 20),

        TextField(
          controller: _nameCtrl,
          textCapitalization: TextCapitalization.words,
          decoration: const InputDecoration(
            labelText: 'Device Name',
            prefixIcon: Icon(Icons.label_outline_rounded),
            helperText: 'e.g. Living Room Socket',
          ),
        ),
        const SizedBox(height: 16),

        TextField(
          controller: _ssidCtrl,
          decoration: const InputDecoration(
            labelText: 'WiFi Network (SSID)',
            prefixIcon: Icon(Icons.wifi_rounded),
            helperText: 'SSID must be 2.4GHz WiFi network',
          ),
        ),
        const SizedBox(height: 16),

        TextField(
          controller: _passCtrl,
          obscureText: true,
          decoration: const InputDecoration(
            labelText: 'WiFi Password',
            prefixIcon: Icon(Icons.lock_outline_rounded),
          ),
        ),
        const SizedBox(height: 16),

        TextField(
          controller: _pinCtrl,
          maxLength: 4,
          keyboardType: TextInputType.number,
          decoration: const InputDecoration(
            labelText: 'Security PIN (BLE/Device)',
            prefixIcon: Icon(Icons.pin_outlined),
            counterText: '',
            helperText: 'Default PIN is 0000',
          ),
        ),
        const SizedBox(height: 28),

        FilledButton.icon(
          onPressed: _submitRegistration,
          icon: const Icon(Icons.check_rounded),
          label: const Text('Register & Provision'),
        ),
      ],
    );
  }

  // ── Step-by-Step Progress Overlay ────────────────────────────────
  Widget _buildProgressOverlay(ColorScheme cs, TextTheme tt) {
    bool isStepDone(String stepName) {
      if (_currentStep == 'success') return true;
      final isNew = _statusChar != null;

      if (isNew) {
        if (stepName == 'writing') return _currentStep != 'writing';
        if (stepName == 'connecting_wifi') {
          return _currentStep == 'connecting_ws' || _currentStep == 'registering';
        }
        if (stepName == 'connecting_ws') return _currentStep == 'registering';
        if (stepName == 'registering') return false;
      } else {
        if (stepName == 'registering') return _currentStep != 'registering';
        if (stepName == 'writing') return _currentStep == 'connecting_ws';
        if (stepName == 'connecting_wifi') return true;
        if (stepName == 'connecting_ws') return false;
      }
      return false;
    }

    bool isStepActive(String stepName) {
      if (stepName == 'connecting_wifi' && _statusChar == null) return false;
      return _currentStep == stepName;
    }

    Widget buildStepRow(String title, String stepKey) {
      final done = isStepDone(stepKey);
      final active = isStepActive(stepKey);

      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 12),
        child: Row(
          children: [
            if (done)
              const CircleAvatar(
                radius: 12,
                backgroundColor: Colors.green,
                child: Icon(Icons.check, size: 14, color: Colors.white),
              )
            else if (active)
              const SizedBox(
                width: 24,
                height: 24,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            else
              CircleAvatar(
                radius: 12,
                backgroundColor: cs.surfaceContainerHighest,
                child: const SizedBox(),
              ),
            const SizedBox(width: 16),
            Text(
              title,
              style: tt.bodyMedium?.copyWith(
                fontWeight: active ? FontWeight.bold : FontWeight.normal,
                color: active
                    ? cs.primary
                    : done
                        ? cs.onSurface
                        : cs.onSurfaceVariant,
              ),
            ),
          ],
        ),
      );
    }

    return Center(
      child: Container(
        padding: const EdgeInsets.all(24),
        constraints: const BoxConstraints(maxWidth: 320),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'Registering Device',
              style: tt.headlineSmall?.copyWith(fontWeight: FontWeight.bold),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 24),

            if (_statusChar == null) ...[
              buildStepRow('Server Registration', 'registering'),
              buildStepRow('Sending Credentials via BLE', 'writing'),
              buildStepRow('Server Connection Sync', 'connecting_ws'),
            ] else ...[
              buildStepRow('Sending Credentials via BLE', 'writing'),
              buildStepRow('WiFi Connection Establishment', 'connecting_wifi'),
              buildStepRow('Server Connection Sync', 'connecting_ws'),
              buildStepRow('Server Registration', 'registering'),
            ],

            const SizedBox(height: 32),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: cs.surfaceContainerLow,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Text(
                _statusMsg,
                style: tt.bodySmall?.copyWith(color: cs.onSurfaceVariant),
                textAlign: TextAlign.center,
              ),
            ),
            const SizedBox(height: 24),

            if (_currentStep == 'failed') ...[
              FilledButton.icon(
                onPressed: () {
                  setState(() {
                    _currentStep = 'idle';
                    _submitting = false;
                  });
                },
                icon: const Icon(Icons.edit_rounded),
                label: const Text('Edit Details & Retry'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
