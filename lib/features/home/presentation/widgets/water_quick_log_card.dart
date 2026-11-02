import 'package:flutter/material.dart';

import '../../../../core/theme/app_dimensions.dart';

/// One-tap water logging card: shows today's cup progress plus a large
/// add-cup button. UI-only; the caller owns cup/goal numbers and the callback.

class WaterQuickLogCard extends StatelessWidget {
  const WaterQuickLogCard({
    super.key,
    required this.currentMl,
    required this.goalMl,
    required this.cupSizeMl,
    required this.onAddCup,
  });

  final int currentMl;
  final int goalMl;
  final int cupSizeMl;
  final VoidCallback? onAddCup;

  double get progress {
    if (goalMl <= 0) {
      return 0.0;
    }
    return (currentMl / goalMl).clamp(0.0, 1.0);
  }

  bool get goalReached => goalMl > 0 && currentMl >= goalMl;

  int get cupsDrunk {
    if (cupSizeMl <= 0) {
      return 0;
    }
    return (currentMl / cupSizeMl).floor();
  }

  int get cupsGoal {
    if (cupSizeMl <= 0) {
      return 0;
    }
    return (goalMl / cupSizeMl).ceil();
  }

  int get remainingMl {
    final int remaining = goalMl - currentMl;
    return remaining > 0 ? remaining : 0;
  }

  @override
  Widget build(BuildContext context) {
    final TextTheme themeText = Theme.of(context).textTheme;
    final ColorScheme scheme = Theme.of(context).colorScheme;

    return Card(
      clipBehavior: Clip.antiAlias,
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Row(
              children: <Widget>[
                Icon(
                  Icons.water_drop_rounded,
                  size: AppIcon.accent,
                  color: scheme.secondary,
                ),
                const SizedBox(width: AppSpacing.sm),
                Flexible(
                  child: Text(
                    'الماء',
                    style: EmphStyles.cardHeading(context),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.md),

            // Big numerals, bold — primary reading line for seniors.
            Text(
              '$cupsDrunk / $cupsGoal كوب',
              style: themeText.bodyLarge?.copyWith(
                fontWeight: AppWeights.bold,
                fontSize: AppTypeScale.timeLarge,
                color: scheme.onSurface,
              ),
            ),
            Text(
              '$currentMl من $goalMl مل',
              style: themeText.bodyMedium,
            ),
            const SizedBox(height: AppSpacing.sm),

            Semantics(
              label: 'تقدّم شرب الماء',
              value: '${(progress * 100).round()} بالمئة',
              child: ClipRRect(
                borderRadius: BorderRadius.circular(AppRadius.progress),
                child: LinearProgressIndicator(
                  value: progress,
                  minHeight: 12.0,
                  backgroundColor:
                      scheme.secondary.withOpacity(0.18),
                  color: scheme.secondary,
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.xs),
            Align(
              alignment: AlignmentDirectional.centerStart,
              child: Text(
                goalReached
                    ? 'وصلت لهدف الماء لليوم. أحسنت!'
                    : 'تبقّى لك $remainingMl مل',
                style: themeText.labelMedium?.copyWith(
                  color: goalReached ? scheme.secondary : scheme.onSurface.withOpacity(0.7),
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.lg),

            SizedBox(
              height: AppTarget.minButtonHeight,
              child: ElevatedButton.icon(
                onPressed: goalReached ? null : onAddCup,
                style: ElevatedButton.styleFrom(
                  minimumSize: const Size.fromHeight(AppTarget.minButtonHeight),
                  // Water action keeps its own accent identity.
                  backgroundColor:
                      goalReached ? scheme.secondary.withOpacity(0.18) : scheme.secondary,
                  foregroundColor:
                      goalReached ? scheme.onSurface : scheme.onSecondary,
                ),
                icon: const Icon(Icons.add_rounded, size: AppIcon.action),
                label: Text(
                  goalReached ? 'اكتمل هدف اليوم' : '+ كوب ماء ($cupSizeMl مل)',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
