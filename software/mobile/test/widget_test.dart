import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:mobile/main.dart';

void main() {
  testWidgets('App boots and shows Maya Smart Home landing',
      (WidgetTester tester) async {
    SharedPreferences.setMockInitialValues({});
    await tester.pumpWidget(const MyApp());
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('Maya Smart Home'), findsOneWidget);
    expect(find.text('Login / Register'), findsOneWidget);
    expect(find.text('Provision Device (BLE)'), findsOneWidget);
  });
}
