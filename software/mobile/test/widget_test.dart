import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:maya_smart_home/main.dart';

void main() {
  testWidgets('App boots and shows Maya Smart Home landing',
      (WidgetTester tester) async {
    SharedPreferences.setMockInitialValues({});
    await tester.pumpWidget(const MayaSmartHomeApp());
    await tester.pump(const Duration(milliseconds: 50));

    // The app will boot up to LoginScreen, which contains the title "Maya Smart Home"
    // and options to login as parent/child, and download links.
    expect(find.text('Maya Smart Home'), findsOneWidget);
  });
}
