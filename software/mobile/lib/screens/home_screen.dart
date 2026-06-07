import 'package:flutter/material.dart';
import '../services/api_service.dart';
import 'provision_screen.dart';
import 'auth_screen.dart';
import 'device_list_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  bool _checkingAuth = true;

  @override
  void initState() {
    super.initState();
    _checkAuth();
  }

  Future<void> _checkAuth() async {
    await ApiService.init();
    if (ApiService.isLoggedIn) {
      if (mounted) {
        Navigator.pushReplacement(
          context,
          MaterialPageRoute(builder: (_) => const DeviceListScreen()),
        );
      }
    } else {
      if (mounted) {
        setState(() {
          _checkingAuth = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_checkingAuth) {
      return const Scaffold(
        body: Center(
          child: CircularProgressIndicator(),
        ),
      );
    }

    return Scaffold(
      appBar: AppBar(title: const Text('Maya Smart Home')),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            ElevatedButton.icon(
              onPressed: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(builder: (context) => const AuthScreen()),
                ).then((_) {
                  // Re-check auth state when returning
                  _checkAuth();
                });
              },
              icon: const Icon(Icons.account_circle),
              label: const Text('Login / Register'),
            ),
            const SizedBox(height: 16),
            ElevatedButton.icon(
              onPressed: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(builder: (context) => const ProvisionScreen()),
                );
              },
              icon: const Icon(Icons.bluetooth),
              label: const Text('Provision Device (BLE)'),
            ),
          ],
        ),
      ),
    );
  }
}
