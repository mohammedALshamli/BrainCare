import 'package:flutter/material.dart';

import '../../../../core/theme/app_dimensions.dart';

/// Prominent card with the next scheduled dose and a single large
/// confirmation action. Purely presentational — receives plain strings and a
/// VoidCallback so Riverpod repositories can be wired later.

class NextDoseHeroCard extends StatelessWidget {
  const NextDoseHeroCard({
    super.key,
    required this.medicationName,
    required this.dosageInstructions,
    required this.scheduledTimeLabel,
    required this.onConfirmDose,
    this.isConfirmed = false,
  });

  final String medicationName;
  final String dosageInstructions;
  final String scheduledTimeLabel;
  final VoidCallback? onConfirmDose;
  final bool isConfirmed;

  String get _heroSemantics {
    final String state = isConfirmed ? 'تم تأكيد الجرعة' : 'لم يتم تأكيد الجرعة بعد';
    return 'الجرعة القادمة، $medicationName، '
        'الساعة $scheduledTimeLabel. $state';
  }

  @override
  Widget build(BuildContext context) {
    final TextTheme themeText = Theme.of(context).textTheme;
    final ColorScheme scheme = Theme.of(context).colorScheme;

    return Semantics(
      container: true,
      label: _heroSemantics,
      button: false,
      child: Card(
        clipBehavior: Clip.antiAlias,
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Text(
                'الجرعة القادمة',
                style: themeText.labelMedium?.copyWith(
                  color: scheme.onSurface.withOpacity(0.7),
                ),
              ),
              const SizedBox(height: AppSpacing.xs),
              Text(
                medicationName,
                style: EmphStyles.cardHeading(context),
                textAlign: TextAlign.start,
              ),
              const SizedBox(height: AppSpacing.sm),
              Text(
                dosageInstructions,
                style: themeText.bodyMedium,
                textAlign: TextAlign.start,
              ),
              const SizedBox(height: AppSpacing.sm),
              Text(
                scheduledTimeLabel,
                style: EmphStyles.doseTime(context).copyWith(
                  color: scheme.primary,
                ),
                textAlign: TextAlign.start,
              ),
              const SizedBox(height: AppSpacing.lg),
              SizedBox(
                height: isConfirmed
                    ? AppTarget.minButtonHeight
                    : AppTarget.heroConfirmHeight,
                child: ElevatedButton.icon(
                  onPressed: isConfirmed ? null : onConfirmDose,
                  style: ElevatedButton.styleFrom(
                    minimumSize: const Size.fromHeight(
                      isConfirmed
                          ? AppTarget.minButtonHeight
                          : AppTarget.heroConfirmHeight,
                    ),
                  ),
                  icon: Icon(
                    isConfirmed ? Icons.check_circle_rounded : Icons.check_rounded,
                    size: AppIcon.action,
                  ),
                  label: Text(
                    isConfirmed ? 'تم التأكيد. أحسنت!' : 'أخذت الدواء',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// Keep the typography/composition helpers importable from widgets.
export '../../../../core/theme/app_typography_builder.dart' show EmphStyles;
