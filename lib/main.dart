import 'package:flutter/material.dart';

import 'core/theme/app_theme.dart';
import 'features/home/presentation/widgets/next_dose_hero_card.dart';
import 'features/home/presentation/widgets/simple_bottom_nav_bar.dart';
import 'features/home/presentation/widgets/water_quick_log_card.dart';

/// Visual-only demo of the three isolated widgets with mock callbacks.
/// Nothing here talks to the network — replace the locals with Riverpod
/// providers when repositories land.

void main() {
  runApp(const _WidgetsDemoApp());
}

class _WidgetsDemoApp extends StatelessWidget {
  const _WidgetsDemoApp();

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'BrainCare Widgets Demo',
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      themeMode: ThemeMode.light,
      supportedLocales: const <Locale>[Locale('ar'), Locale('en')],
      locale: const Locale('ar'),
      home: const _WidgetsDemoScreen(),
    );
  }
}

class _WidgetsDemoScreen extends StatefulWidget {
  const _WidgetsDemoScreen();

  @override
  State<_WidgetsDemoScreen> createState() => _WidgetsDemoScreenState();
}

class _WidgetsDemoScreen extends State<_WidgetsDemoScreen> {
  int _navIndex = 0;
  int _currentMl = 750;
  bool _doseConfirmed = false;

  final List<BottomNavTab> _tabs = const <BottomNavTab>[
    BottomNavTab(
      label: 'اليوم',
      icon: Icons.today_outlined,
      selectedIcon: Icons.today_rounded,
      semanticsLabel: 'اليوم',
    ),
    BottomNavTab(
      label: 'الأدوية',
      icon: Icons.medication_outlined,
      selectedIcon: Icons.medication_rounded,
      semanticsLabel: 'الأدوية',
    ),
    BottomNavTab(
      label: 'الماء',
      icon: Icons.water_drop_outlined,
      selectedIcon: Icons.water_drop_rounded,
      semanticsLabel: 'الماء',
    ),
  ];

  void _mockConfirmDose() {
    setState(() => _doseConfirmed = true);
  }

  void _mockAddCup() {
    setState(() => _currentMl = _currentMl + 250);
  }

  @override
  Widget build(BuildContext context) {
    return Directionality(
      textDirection: TextDirection.rtl,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('أهلاً بك، الحاج أحمد'),
        ),
        body: SafeArea(
          child: ListView(
            padding: const EdgeInsets.all(24.0),
            children: <Widget>[
              NextDoseHeroCard(
                medicationName: 'كونكور 5 ملغ',
                dosageInstructions: 'قرص واحد بعد الفطور',
                scheduledTimeLabel: '08:00 صباحًا',
                isConfirmed: _doseConfirmed,
                onConfirmDose: _mockConfirmDose,
              ),
              const SizedBox(height: 24.0),
              WaterQuickLogCard(
                currentMl: _currentMl,
                goalMl: 2000,
                cupSizeMl: 250,
                onAddCup: _mockAddCup,
              ),
            ],
          ),
        ),
        bottomNavigationBar: SimpleBottomNavBar(
          tabs: _tabs,
          selectedIndex: _navIndex,
          onTabSelected: (int index) => setState(() => _navIndex = index),
        ),
      ),
    );
  }
}
