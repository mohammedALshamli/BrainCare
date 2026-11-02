import 'package:flutter/material.dart';

import 'app_colors.dart';
import 'app_dimensions.dart';

/// Builds the Cairo-driven text scale. Colors come from the caller so the
/// same scale serves light and dark mode without widget-level overrides.
/// All sizes enforce the elderly-readability minimums (titles >= 26, body >= 20).
TextTheme buildCairoTextTheme({
  required Color textPrimary,
  required Color textMuted,
}) {
  TextStyle base({
    required double size,
    required FontWeight weight,
    required Color color,
    double height = 1.4,
    double letterSpacing = 0.0,
  }) {
    return TextStyle(
      fontFamily: AppFont.family,
      fontSize: size,
      fontWeight: weight,
      color: color,
      height: height,
      letterSpacing: letterSpacing,
    );
  }

  return TextTheme(
    displaySmall: base(size: AppTypeScale.titlePage, weight: AppWeights.bold, color: textPrimary),
    headlineMedium: base(size: AppTypeScale.titleSection, weight: AppWeights.bold, color: textPrimary),
    titleLarge: base(size: AppTypeScale.titleItem, weight: AppWeights.semiBold, color: textPrimary),
    bodyLarge: base(size: AppTypeScale.body, weight: AppWeights.regular, color: textPrimary),
    bodyMedium: base(size: AppTypeScale.bodySmall, weight: AppWeights.regular, color: textMuted),
    labelLarge: base(size: AppTypeScale.label, weight: AppWeights.bold, color: textPrimary,
        height: 1.2),
    labelMedium: base(size: AppTypeScale.caption, weight: AppWeights.medium, color: textMuted),
  );
}

/// Convenience semantic styles for widget-level emphasis (medicine names,
/// scheduled times). Widgets compose these with theme colors at runtime.

class EmphStyles {
  static TextStyle? cardHeading(BuildContext context) {
    final TextStyle base = Theme.of(context).textTheme.headlineMedium ?? const TextStyle(fontSize: 26);
    return base.copyWith(fontWeight: AppWeights.bold, height: 1.3);
  }

  static TextStyle? doseTime(BuildContext context) {
    final TextStyle fallback = Theme.of(context).textTheme.bodyLarge ?? const TextStyle(fontSize: 22);
    return fallback.copyWith(fontSize: AppTypeScale.timeLarge, fontWeight: AppWeights.bold);
  }
}
