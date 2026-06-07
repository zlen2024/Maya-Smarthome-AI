import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../services/api_service.dart';

class ControlScreen extends StatefulWidget {
  final String deviceId;
  final String deviceName;

  const ControlScreen({
    super.key,
    required this.deviceId,
    required this.deviceName,
  });

  @override
  State<ControlScreen> createState() => _ControlScreenState();
}

class _ControlScreenState extends State<ControlScreen> {
  final TextEditingController _pinController = TextEditingController();
  StreamSubscription? _broadcastSubscription;

  String _statusLog = "Loading device status...";
  String _ch1 = "off";
  String _ch2 = "off";
  String _ch3 = "off";

  @override
  void initState() {
    super.initState();
    _loadSettings();
    _fetchChannelStates();
    _listenToBroadcasts();
  }

  @override
  void dispose() {
    _broadcastSubscription?.cancel();
    _pinController.dispose();
    super.dispose();
  }

  Future<void> _loadSettings() async {
    final prefs = await SharedPreferences.getInstance();
    _pinController.text = prefs.getString('device_pin') ?? "0000";
    setState(() {});
  }

  void _listenToBroadcasts() {
    _broadcastSubscription = ApiService.broadcasts.listen((data) {
      if (data['device_id'] == widget.deviceId) {
        setState(() {
          if (data['type'] == 'device_update') {
            _ch1 = data['ch1'] ?? _ch1;
            _ch2 = data['ch2'] ?? _ch2;
            _ch3 = data['ch3'] ?? _ch3;
            _statusLog = "Status updated in real-time";
          } else if (data['type'] == 'device_offline') {
            _statusLog = "Device went offline";
          }
        });
      }
    });
  }

  Future<void> _fetchChannelStates() async {
    try {
      final response = await ApiService.get('/api/devices/${widget.deviceId}');
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        setState(() {
          _ch1 = data['ch1'] ?? 'off';
          _ch2 = data['ch2'] ?? 'off';
          _ch3 = data['ch3'] ?? 'off';
          final online = data['online'] ?? false;
          _statusLog = online ? "Connected / Online" : "Offline";
        });
      } else {
        setState(() {
          _statusLog = "Failed to load device: ${response.statusCode}";
        });
      }
    } catch (e) {
      setState(() {
        _statusLog = "Error checking status: $e";
      });
    }
  }

  Future<void> _sendCommand(String cmd, {int? channel}) async {
    setState(() {
      _statusLog = "Sending command: $cmd...";
    });

    try {
      // Save device_pin for convenience
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('device_pin', _pinController.text);

      final body = {
        "cmd": cmd,
        if (channel != null) "channel": channel,
        "pin": _pinController.text,
      };

      final response = await ApiService.post('/api/devices/${widget.deviceId}/command', body);
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        final status = data['status'] ?? '';

        if (status == 'ok') {
          setState(() {
            _ch1 = data['ch1'] ?? _ch1;
            _ch2 = data['ch2'] ?? _ch2;
            _ch3 = data['ch3'] ?? _ch3;
            _statusLog = "Command successful: $cmd";
          });
        } else if (status == 'blocked') {
          setState(() => _statusLog = "ERROR: Device is blocked by admin");
        } else if (status == 'not_connected') {
          setState(() => _statusLog = "ERROR: Device is not connected");
        } else if (status == 'timeout') {
          setState(() => _statusLog = "ERROR: Device timeout");
        } else {
          setState(() => _statusLog = "ERROR: $status");
        }
      } else {
        final data = jsonDecode(response.body);
        final detail = data['detail'] ?? "Error ${response.statusCode}";
        setState(() => _statusLog = "ERROR: $detail");
      }
    } catch (e) {
      setState(() {
        _statusLog = "Connection error: $e";
      });
    }
  }

  void _sendChannelCommand(int channel, bool turnOn) {
    _sendCommand(turnOn ? "output_on" : "output_off", channel: channel);
    setState(() {
      if (channel == 1) _ch1 = turnOn ? "on" : "off";
      if (channel == 2) _ch2 = turnOn ? "on" : "off";
      if (channel == 3) _ch3 = turnOn ? "on" : "off";
    });
  }

  Color _chColor(int ch) {
    return [Colors.blue, Colors.green, Colors.orange][ch - 1];
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.deviceName),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.grey[200],
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                _statusLog,
                style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14),
                textAlign: TextAlign.center,
              ),
            ),
            const SizedBox(height: 20),
            TextField(
              controller: _pinController,
              decoration: const InputDecoration(
                labelText: "Device PIN (For Relay Access)",
                border: OutlineInputBorder(),
                prefixIcon: Icon(Icons.lock_outline),
              ),
              obscureText: true,
            ),
            const SizedBox(height: 30),
            const Text(
              "Relay Channels",
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 16),
            _channelCard(1, "Channel 1", _ch1, _chColor(1), Icons.power_settings_new),
            const SizedBox(height: 10),
            _channelCard(2, "Channel 2", _ch2, _chColor(2), Icons.power_settings_new),
            const SizedBox(height: 10),
            _channelCard(3, "Channel 3", _ch3, _chColor(3), Icons.power_settings_new),
            const SizedBox(height: 24),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceEvenly,
              children: [
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: () => _sendCommand("all_on"),
                    icon: const Icon(Icons.check_circle_outline, color: Colors.white),
                    label: const Text("All On"),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.green,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 12),
                    ),
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: () => _sendCommand("all_off"),
                    icon: const Icon(Icons.remove_circle_outline, color: Colors.white),
                    label: const Text("All Off"),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.red,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 12),
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 24),
            OutlinedButton.icon(
              onPressed: _fetchChannelStates,
              icon: const Icon(Icons.refresh),
              label: const Text("Refresh Status"),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 12),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _channelCard(int ch, String label, String state, Color color, IconData icon) {
    final isOn = state == "on";
    return Card(
      elevation: isOn ? 3 : 1,
      color: isOn ? color.withOpacity(0.12) : Colors.white,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(10),
        side: BorderSide(
          color: isOn ? color.withOpacity(0.5) : Colors.grey[300]!,
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Row(
          children: [
            CircleAvatar(
              backgroundColor: isOn ? color.withOpacity(0.2) : Colors.grey[200],
              child: Icon(icon, color: isOn ? color : Colors.grey[600]),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(label, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
                  Text(
                    isOn ? "ON" : "OFF",
                    style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                      color: isOn ? color : Colors.grey[600],
                    ),
                  ),
                ],
              ),
            ),
            Switch(
              value: isOn,
              activeColor: color,
              onChanged: (val) => _sendChannelCommand(ch, val),
            ),
          ],
        ),
      ),
    );
  }
}
