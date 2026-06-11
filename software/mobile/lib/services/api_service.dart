import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

/// Centralized API service with hardcoded production server URL.
/// All REST and WebSocket communication flows through this class.
class ApiService {
  // ── Production Server (hardcoded) ──────────────────────────────
  static const String baseUrl = 'https://maya-smarthome-ai.fly.dev';
  static const String wsUrl = 'wss://maya-smarthome-ai.fly.dev';

  // ── Session State ──────────────────────────────────────────────
  static String token = '';
  static int? houseId;
  static bool isChild = false;
  static String userName = '';
  static String userRole = 'parent';
  static int? accId;

  // ── Multi-House State ──────────────────────────────────────────
  static List<Map<String, dynamic>> houses = [];
  static Map<String, dynamic>? activeHouse;

  // ── WebSocket Channel Reference ────────────────────────────────
  static WebSocketChannel? activeChannel;

  // ── WebSocket Broadcast Relay ──────────────────────────────────
  static final StreamController<Map<String, dynamic>> _broadcastController =
      StreamController<Map<String, dynamic>>.broadcast();

  static Stream<Map<String, dynamic>> get broadcasts =>
      _broadcastController.stream;

  static void emitBroadcast(Map<String, dynamic> data) {
    _broadcastController.add(data);
  }

  // ── Chat Broadcast Relay ───────────────────────────────────────
  static final StreamController<Map<String, dynamic>> _chatController =
      StreamController<Map<String, dynamic>>.broadcast();

  static Stream<Map<String, dynamic>> get chatBroadcasts =>
      _chatController.stream;

  static void emitChat(Map<String, dynamic> data) =>
      _chatController.add(data);

  // ── Initialization ─────────────────────────────────────────────
  static Future<void> init() async {
    final prefs = await SharedPreferences.getInstance();
    token = prefs.getString('auth_token') ?? '';
    houseId = prefs.getInt('house_id');
    isChild = prefs.getBool('is_child') ?? false;
    userName = prefs.getString('user_name') ?? '';
    userRole = prefs.getString('user_role') ?? 'parent';
    accId = prefs.getInt('acc_id');

    // Restore activeHouse
    final activeHouseJson = prefs.getString('active_house');
    if (activeHouseJson != null) {
      try {
        activeHouse = jsonDecode(activeHouseJson) as Map<String, dynamic>;
      } catch (_) {
        activeHouse = null;
      }
    }
  }

  static bool get isLoggedIn => token.isNotEmpty;
  static bool get hasHouse => houseId != null;

  // ── Credential Persistence ─────────────────────────────────────
  static Future<void> saveCredentials({
    required String jwtToken,
    required int? house,
    required String name,
    required String role,
    int? accountId,
    bool child = false,
  }) async {
    token = jwtToken;
    houseId = house;
    userName = name;
    userRole = role;
    isChild = child;
    accId = accountId;

    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('auth_token', jwtToken);
    if (house != null) {
      await prefs.setInt('house_id', house);
    } else {
      await prefs.remove('house_id');
    }
    await prefs.setString('user_name', name);
    await prefs.setString('user_role', role);
    await prefs.setBool('is_child', child);
    if (accountId != null) await prefs.setInt('acc_id', accountId);

    // Persist activeHouse
    if (activeHouse != null) {
      await prefs.setString('active_house', jsonEncode(activeHouse));
    }
  }

  static Future<void> logout() async {
    token = '';
    houseId = null;
    isChild = false;
    userName = '';
    userRole = 'parent';
    accId = null;
    houses = [];
    activeHouse = null;
    activeChannel = null;

    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('auth_token');
    await prefs.remove('house_id');
    await prefs.remove('user_name');
    await prefs.remove('user_role');
    await prefs.remove('is_child');
    await prefs.remove('acc_id');
    await prefs.remove('active_house');
  }

  // ── HTTP Helpers ───────────────────────────────────────────────
  static Map<String, String> get _authHeaders => {
        'Authorization': 'Bearer $token',
        'Content-Type': 'application/json',
      };

  static Future<http.Response> get(String path) {
    return http.get(Uri.parse('$baseUrl$path'), headers: _authHeaders);
  }

  static Future<http.Response> post(String path, Map<String, dynamic> body) {
    return http.post(
      Uri.parse('$baseUrl$path'),
      headers: _authHeaders,
      body: jsonEncode(body),
    );
  }

  static Future<http.Response> put(String path, Map<String, dynamic> body) {
    return http.put(
      Uri.parse('$baseUrl$path'),
      headers: _authHeaders,
      body: jsonEncode(body),
    );
  }

  static Future<http.Response> delete(String path) {
    return http.delete(Uri.parse('$baseUrl$path'), headers: _authHeaders);
  }

  // ── Auth ────────────────────────────────────────────────────────
  static Future<Map<String, dynamic>> login(
      String email, String password) async {
    final res = await http.post(
      Uri.parse('$baseUrl/api/auth/login'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'email': email, 'password': password}),
    );
    if (res.statusCode != 200) {
      final data = jsonDecode(res.body);
      throw Exception(data['detail'] ?? 'Login failed');
    }
    return jsonDecode(res.body);
  }

  static Future<Map<String, dynamic>> childLogin(
      int childId, String pin) async {
    final res = await http.post(
      Uri.parse('$baseUrl/api/children/$childId/login'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'pin': pin}),
    );
    if (res.statusCode != 200) {
      final data = jsonDecode(res.body);
      throw Exception(data['detail'] ?? 'Invalid Child ID or PIN');
    }
    return jsonDecode(res.body);
  }

  static Future<Map<String, dynamic>> getProfile() async {
    final res = await get('/api/auth/me');
    if (res.statusCode != 200) throw Exception('Session expired');
    return jsonDecode(res.body);
  }

  // ── Houses ─────────────────────────────────────────────────────
  static Future<List<Map<String, dynamic>>> getHouses() async {
    final res = await get('/api/houses');
    if (res.statusCode != 200) throw Exception('Failed to fetch houses');
    final data = jsonDecode(res.body);
    final list = (data['houses'] as List)
        .map((e) => Map<String, dynamic>.from(e as Map))
        .toList();
    houses = list;

    // Set activeHouse to the one with is_active == true
    activeHouse = null;
    for (final h in houses) {
      if (h['is_active'] == true) {
        activeHouse = h;
        houseId = h['house_id'] as int?;
        break;
      }
    }
    // Fallback: use first house if none is marked active
    if (activeHouse == null && houses.isNotEmpty) {
      activeHouse = houses.first;
      houseId = houses.first['house_id'] as int?;
    }

    return houses;
  }

  static Future<Map<String, dynamic>> createHouse(String location) async {
    final res = await post('/api/houses', {'location': location});
    if (res.statusCode != 200 && res.statusCode != 201) {
      final data = jsonDecode(res.body);
      throw Exception(data['detail'] ?? 'Failed to create house');
    }
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    // Refresh houses list
    await getHouses();
    return data;
  }

  static Future<Map<String, dynamic>> joinHouse(
      int houseId, String pin) async {
    final res = await post('/api/houses/join', {
      'house_id': houseId,
      'pin': pin,
    });
    if (res.statusCode != 200) {
      final data = jsonDecode(res.body);
      throw Exception(data['detail'] ?? 'Failed to join house');
    }
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    // Refresh houses list
    await getHouses();
    return data;
  }

  static Future<void> switchHouse(int houseId) async {
    final res = await post('/api/houses/switch', {'house_id': houseId});
    if (res.statusCode != 200) {
      final data = jsonDecode(res.body);
      throw Exception(data['detail'] ?? 'Failed to switch house');
    }
    // Update local state
    await getHouses();
  }

  static Future<List<Map<String, dynamic>>> getMembers(int houseId) async {
    final res = await get('/api/houses/$houseId/members');
    if (res.statusCode != 200) throw Exception('Failed to fetch members');
    final data = jsonDecode(res.body);
    return (data['members'] as List)
        .map((e) => Map<String, dynamic>.from(e as Map))
        .toList();
  }

  static Future<void> kickMember(int houseId, int accId) async {
    final res = await delete('/api/houses/$houseId/members/$accId');
    if (res.statusCode != 200) {
      final data = jsonDecode(res.body);
      throw Exception(data['detail'] ?? 'Failed to remove member');
    }
  }

  static Future<String> resetPin(int houseId) async {
    final res = await post('/api/houses/$houseId/reset-pin', {});
    if (res.statusCode != 200) {
      final data = jsonDecode(res.body);
      throw Exception(data['detail'] ?? 'Failed to reset PIN');
    }
    final data = jsonDecode(res.body);
    return data['join_pin'] as String;
  }

  static Future<Map<String, dynamic>> getChatHistory(int houseId,
      {int? before}) async {
    String path = '/api/houses/$houseId/chat';
    if (before != null) path += '?before=$before';
    final res = await get(path);
    if (res.statusCode != 200) throw Exception('Failed to fetch chat');
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  // ── Devices ─────────────────────────────────────────────────────
  static Future<List<dynamic>> getDevices() async {
    final res = await get('/api/devices');
    if (res.statusCode != 200) throw Exception('Failed to fetch devices');
    final data = jsonDecode(res.body);
    return data['devices'] ?? [];
  }

  static Future<Map<String, dynamic>> getDevice(String deviceId) async {
    final res = await get('/api/devices/$deviceId');
    if (res.statusCode != 200) throw Exception('Failed to fetch device');
    return jsonDecode(res.body);
  }

  static Future<Map<String, dynamic>> sendCommand(String deviceId, String cmd,
      {int? channel}) async {
    final body = <String, dynamic>{'cmd': cmd};
    if (channel != null) body['channel'] = channel;
    final res = await post('/api/devices/$deviceId/command', body);
    final data = jsonDecode(res.body);
    if (res.statusCode != 200) {
      throw Exception(data['detail'] ?? 'Command failed');
    }
    return data;
  }

  static Future<Map<String, dynamic>> registerDevice(
      String deviceId, String name,
      {double price = 0.0, String pin = '0000'}) async {
    final res = await post('/api/devices/register', {
      'device_id': deviceId,
      'name': name,
      'price': price,
      'pin': pin,
    });
    final data = jsonDecode(res.body);
    if (res.statusCode != 200) {
      throw Exception(data['detail'] ?? 'Device registration failed');
    }
    return data;
  }

  static Future<void> deleteDevice(String deviceId) async {
    final res = await delete('/api/devices/$deviceId');
    if (res.statusCode != 200) {
      final data = jsonDecode(res.body);
      throw Exception(data['detail'] ?? 'Failed to delete device');
    }
  }

  // ── Children ────────────────────────────────────────────────────
  static Future<List<dynamic>> getChildren() async {
    final res = await get('/api/children');
    if (res.statusCode != 200) throw Exception('Failed to fetch children');
    final data = jsonDecode(res.body);
    return data['children'] ?? [];
  }

  static Future<Map<String, dynamic>> createChild(
      String name, String pin) async {
    final res = await post('/api/children', {'name': name, 'pin': pin});
    final data = jsonDecode(res.body);
    if (res.statusCode != 200) {
      throw Exception(data['detail'] ?? 'Failed to create child account');
    }
    return data;
  }

  // ── Relays & Permissions ────────────────────────────────────────
  static Future<List<dynamic>> getRelays() async {
    final res = await get('/api/relays');
    if (res.statusCode != 200) throw Exception('Failed to fetch relays');
    final data = jsonDecode(res.body);
    return data['relays'] ?? [];
  }

  static Future<List<dynamic>> getPermissions({int? childId}) async {
    String path = '/api/permissions';
    if (childId != null) path += '?child_id=$childId';
    final res = await get(path);
    if (res.statusCode != 200) throw Exception('Failed to fetch permissions');
    final data = jsonDecode(res.body);
    return data['permissions'] ?? [];
  }

  static Future<void> createPermission(
      int childId, int relayId, bool isAllowed) async {
    final res = await post('/api/permissions', {
      'child_id': childId,
      'relay_id': relayId,
      'is_allowed': isAllowed,
    });
    if (res.statusCode != 200) {
      final data = jsonDecode(res.body);
      throw Exception(data['detail'] ?? 'Failed to set permission');
    }
  }

  static Future<void> updatePermission(int permId, bool isAllowed) async {
    final res =
        await put('/api/permissions/$permId', {'is_allowed': isAllowed});
    if (res.statusCode != 200) {
      final data = jsonDecode(res.body);
      throw Exception(data['detail'] ?? 'Failed to update permission');
    }
  }
}
