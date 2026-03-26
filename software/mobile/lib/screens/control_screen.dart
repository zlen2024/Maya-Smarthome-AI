import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

class ControlScreen extends StatefulWidget {
  const ControlScreen({super.key});

  @override
  State<ControlScreen> createState() => _ControlScreenState();
}

class _ControlScreenState extends State<ControlScreen> {
  final TextEditingController _urlController = TextEditingController(text: "ws://192.168.1.100:8000/ws");
  final TextEditingController _deviceIdController = TextEditingController(text: "esp32-9f83b1c1");

  WebSocketChannel? _channel;
  bool _isConnected = false;
  String _statusLog = "Disconnected";

  void _connect() {
    if (_urlController.text.isEmpty) return;

    try {
      _channel = WebSocketChannel.connect(
        Uri.parse(_urlController.text),
      );

      setState(() {
        _isConnected = true;
        _statusLog = "Connected to Server";
      });

      // Identify self to the server (using a dummy mobile client ID for routing)
      _channel!.sink.add(jsonEncode({
        "id": "mobile-client-01",
        "status": "online"
      }));

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
        "cmd": cmd
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
              child: Text(_statusLog, style: const TextStyle(fontWeight: FontWeight.bold)),
            ),
            const SizedBox(height: 20),

            TextField(
              controller: _urlController,
              decoration: const InputDecoration(labelText: "WebSocket Server URL"),
              enabled: !_isConnected,
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
                style: ElevatedButton.styleFrom(backgroundColor: Colors.red, foregroundColor: Colors.white),
                child: const Text("Disconnect"),
              ),

            const SizedBox(height: 40),

            if (_isConnected) ...[
              const Text("Device Commands", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
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
            ]
          ],
        ),
      ),
    );
  }
}
