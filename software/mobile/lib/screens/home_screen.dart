import 'package:flutter/material.dart';
import 'provision_screen.dart';
import 'control_screen.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('ESP32 Dashboard')),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            ElevatedButton(
              onPressed: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(builder: (context) => const ProvisionScreen()),
                );
              },
              child: const Text('Provision Device (BLE)'),
            ),
            const SizedBox(height: 20),
            ElevatedButton(
              onPressed: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(builder: (context) => const ControlScreen()),
                );
              },
              child: const Text('Control Device (WebSocket)'),
            ),
          ],
        ),
      ),
    );
  }
}
