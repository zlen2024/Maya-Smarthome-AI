import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'dart:convert';
import 'package:http/http.dart' as http;

class ControlScreen extends StatefulWidget {
  const ControlScreen({super.key});

  @override
  State<ControlScreen> createState() => _ControlScreenState();
}

class _ControlScreenState extends State<ControlScreen> {
  final TextEditingController _urlController = TextEditingController();
  final TextEditingController _pinController = TextEditingController();
  final TextEditingController _deviceIdController = TextEditingController(
    text: "esp32-9f83b1c1",
  );

  WebSocketChannel? _channel;
  bool _isConnected = false;
  String _statusLog = "Disconnected";
  String _ledStatus = "unknown";

  @override
  void initState() {
    super.initState();
    _loadSettings();
  }

  Future<void> _loadSettings() async {
    final prefs = await SharedPreferences.getInstance();
    _urlController.text =
        prefs.getString('ws_url') ?? "ws://192.168.1.100:8000/ws";
    _pinController.text = prefs.getString('device_pin') ?? "0000";
    _deviceIdController.text = prefs.getString('device_id') ?? "esp32-9f83b1c1";
    setState(() {});
  }

  Future<void> _fetchLedStatus() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final url = prefs.getString('ws_url') ?? "ws://192.168.1.100:8000/ws";
      final uri = Uri.parse(
        url.replaceFirst('ws://', 'http://').replaceFirst('/ws', ''),
      );
      final deviceId = _deviceIdController.text;

      final response = await http.get(
        Uri.parse(
          '${uri.toString().replaceAll(uri.path, '')}/device/$deviceId/status',
        ),
      );
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        setState(() {
          _ledStatus = data['led_status'] ?? 'unknown';
        });
      }
    } catch (e) {
      print("Failed to fetch LED status: $e");
    }
  }

  void _connect() {
    if (_urlController.text.isEmpty) return;

    try {
      _channel = WebSocketChannel.connect(Uri.parse(_urlController.text));

      setState(() {
        _isConnected = true;
        _statusLog = "Connected to Server";
      });

      _channel!.stream.listen((message) {
        print("Received: $message");
        final data = jsonDecode(message);
        if (data['led'] != null) {
          setState(() {
            _ledStatus = data['led'];
          });
        }
        if (data['status'] == 'pin_mismatch') {
          setState(() {
            _statusLog = "ERROR: PIN Mismatch!";
          });
        }
      });

      _channel!.sink.add(
        jsonEncode({"id": "mobile-client-01", "status": "online"}),
      );

      _fetchLedStatus();
    } catch (e) {
      setState(() {
        _statusLog = "Connection Error: $e";
      });
    }
  }

  void _disconnect() {
    if (_channel != null) {
      _channel!.sink.close();
      setState(() {
        _isConnected = false;
        _statusLog = "Disconnected";
      });
    }
  }

  void _sendCommand(String cmd) {
    if (_channel != null && _deviceIdController.text.isNotEmpty) {
      final payload = jsonEncode({
        "id": "mobile-client-01",
        "target_id": _deviceIdController.text,
        "cmd": cmd,
        "pin": _pinController.text,
      });
      _channel!.sink.add(payload);
      setState(() {
        _statusLog = "Sent command: $cmd to ${_deviceIdController.text}";
      });
    }
  }

  @override
  void dispose() {
    _channel?.sink.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text("Device Control")),
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

            TextField(
              controller: _urlController,
              decoration: const InputDecoration(
                labelText: "WebSocket Server URL",
              ),
              enabled: !_isConnected,
            ),
            TextField(
              controller: _pinController,
              decoration: const InputDecoration(labelText: "PIN"),
            ),
            TextField(
              controller: _deviceIdController,
              decoration: const InputDecoration(labelText: "Target Device ID"),
            ),
            const SizedBox(height: 20),

            if (!_isConnected)
              ElevatedButton(
                onPressed: _connect,
                child: const Text("Connect to Server"),
              )
            else
              ElevatedButton(
                onPressed: _disconnect,
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.red,
                  foregroundColor: Colors.white,
                ),
                child: const Text("Disconnect"),
              ),

            const SizedBox(height: 40),

            if (_isConnected) ...[
              const Text(
                "LED Status",
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 10),
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(
                    _ledStatus == "on"
                        ? Icons.lightbulb
                        : Icons.lightbulb_outline,
                    size: 60,
                    color: _ledStatus == "on" ? Colors.amber : Colors.grey,
                  ),
                  const SizedBox(width: 20),
                  Text(
                    _ledStatus.toUpperCase(),
                    style: TextStyle(
                      fontSize: 24,
                      fontWeight: FontWeight.bold,
                      color: _ledStatus == "on" ? Colors.amber : Colors.grey,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 20),
              Switch(
                value: _ledStatus == "on",
                onChanged: (value) {
                  _sendCommand(value ? "led_on" : "led_off");
                },
              ),
              const SizedBox(height: 20),
              const Text(
                "Device Commands",
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 20),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                children: [
                  ElevatedButton(
                    onPressed: () => _sendCommand("led_on"),
                    child: const Text("LED ON"),
                  ),
                  ElevatedButton(
                    onPressed: () => _sendCommand("led_off"),
                    child: const Text("LED OFF"),
                  ),
                ],
              ),
              const SizedBox(height: 20),
              ElevatedButton(
                onPressed: () => _sendCommand("toggle"),
                child: const Text("TOGGLE LED"),
              ),
              const SizedBox(height: 20),
              ElevatedButton(
                onPressed: () => _sendCommand("reboot"),
                style: ElevatedButton.styleFrom(backgroundColor: Colors.orange),
                child: const Text("REBOOT DEVICE"),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
