import 'package:flutter/material.dart';

import '../../../../core/theme/app_dimensions.dart';

/// A single bottom-nav tab entry. `unselectedIcon`/`selectedIcon` allow
/// filled/outline pairs so selection is conveyed visually and by screen readers.

class BottomNavTab {
  const BottomNavTab({
    required this.label,
    required this.icon,
    required this.selectedIcon,
    required this.semanticsLabel,
  });

  final String label;
  final IconData icon;
  final IconData selectedIcon;
  final String semanticsLabel;
}

/// Maximum three tabs by design (اليوم، الأدوية، الماء) — asserted below so
/// the elderly-simple information architecture cannot silently grow.
///
/// Purely presentational: owns no routing state; the caller stores the index.

class SimpleBottomNavBar extends StatelessWidget {
  const SimpleBottomNavBar({
    super.key,
    required this.tabs,
    required this.selectedIndex,
    required this.onTabSelected,
  }) : assert(
          tabs.length <= 3,
          'SimpleBottomNavBar supports a maximum of 3 tabs',
        );

  final List<BottomNavTab> tabs;
  final int selectedIndex;
  final ValueChanged<int> onTabSelected;

  @override
  Widget build(BuildContext context) {
    final ColorScheme scheme = Theme.of(context).colorScheme;

    return Semantics(
      container: true,
      child: Material(
        color: scheme.surface,
        shadowColor: scheme.shadow,
        child: SafeArea(
          top: false,
          child: SizedBox(
            height: AppTarget.navBarHeight,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: List<Widget>.generate(tabs.length, (int index) {
                return _NavTabButton(
                  tab: tabs[index],
                  isSelected: index == selectedIndex,
                  onTap: () => onTabSelected(index),
                );
              }),
            ),
          ),
        ),
      ),
    );
  }
}

class _NavTabButton extends StatelessWidget {
  const _NavTabButton({
    required this.tab,
    required this.isSelected,
    required this.onTap,
  });

  final BottomNavTab tab;
  final bool isSelected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final ColorScheme scheme = Theme.of(context).colorScheme;
    final Color color = isSelected ? scheme.primary : scheme.onSurface.withOpacity(0.55);

    return Expanded(
      child: Semantics(
        button: true,
        selected: isSelected,
        label: tab.semanticsLabel,
        child: InkWell(
          onTap: onTap,
          child: IconTheme.merge(
            data: IconThemeData(color: color, size: AppIcon.nav),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: <Widget>[
                Icon(isSelected ? tab.selectedIcon : tab.icon),
                const SizedBox(height: AppSpacing.xxs),
                Text(
                  tab.label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.labelMedium?.copyWith(
                        color: color,
                        fontWeight:
                            isSelected ? AppWeights.bold : AppWeights.medium,
                      ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
