import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../screens/voice_overlay_screen.dart';
import 'api_service.dart';

/// Bridges the Quick Settings tile to the voice overlay. The native tile sets a
/// pending flag when it launches/resumes the app; we pull (and clear) it on
/// every resume and on demand, then open the overlay. Also the single entry
/// point the mic FAB uses, so there's one way to start voice.
class VoiceTrigger with WidgetsBindingObserver {
  VoiceTrigger._();
  static final VoiceTrigger instance = VoiceTrigger._();

  static const MethodChannel _channel = MethodChannel('maya/voice');
  static final GlobalKey<NavigatorState> navigatorKey =
      GlobalKey<NavigatorState>();

  bool _checking = false;

  void init() => WidgetsBinding.instance.addObserver(this);

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) checkPending();
  }

  /// Ask native whether the app was launched via the tile; if so, open voice.
  Future<void> checkPending() async {
    if (_checking) return;
    _checking = true;
    try {
      final launch =
          await _channel.invokeMethod<bool>('consumeVoiceLaunch') ?? false;
      if (launch) open();
    } catch (_) {
      // Channel not ready / non-Android: ignore.
    } finally {
      _checking = false;
    }
  }

  /// Open the voice overlay (used by the tile and the mic FAB).
  void open() {
    if (VoiceOverlayScreen.isOpen) return;
    if (!ApiService.isLoggedIn) return;
    final nav = navigatorKey.currentState;
    if (nav == null) return;
    nav.push(MaterialPageRoute(
      fullscreenDialog: true,
      builder: (_) => const VoiceOverlayScreen(),
    ));
  }
}
