import 'package:flutter/material.dart';

import 'app_colors.dart';
import 'app_dimensions.dart';
import 'app_typography_builder.dart';

/// BrainCare elderly-first themes.
///   Light: white cards, deep green primary, charcoal text.
///   Dark:  true OLED black, bright emerald accents, near-white text.

class AppTheme {
  const AppTheme._();

  static ThemeData light() {
    return _build(
      backgroundColor: AppColorsLight.background,
      surface: AppColorsLight.surface,
      surfaceTint: AppColorsLight.surfaceTint,
      textPrimary: AppColorsLight.textPrimary,
      textMuted: AppColorsLight.textMuted,
      onPrimary: AppColorsLight.onPrimary,
      primary: AppColorsLight.primary,
      primaryPressed: AppColorsLight.primaryPressed,
      primaryContainer: AppColorsLight.primaryContainer,
      onPrimaryContainer: AppColorsLight.onPrimaryContainer,
      water: AppColorsLight.water,
      waterContainer: AppColorsLight.waterContainer,
      border: AppColorsLight.border,
      danger: AppColorsLight.danger,
      shadowColor: AppColorsLight.shadow,
    );
  }

  static ThemeData dark() {
    return _build(
      backgroundColor: AppColorsDark.background,
      surface: AppColorsDark.surface,
      surfaceTint: AppColorsDark.surfaceTint,
      textPrimary: AppColorsDark.textPrimary,
      textMuted: AppColorsDark.textMuted,
      onPrimary: AppColorsDark.onPrimary,
      primary: AppColorsDark.primary,
      primaryPressed: AppColorsDark.primaryPressed,
      primaryContainer: AppColorsDark.primaryContainer,
      onPrimaryContainer: AppColorsDark.onPrimaryContainer,
      water: AppColorsDark.water,
      waterContainer: AppColorsDark.waterContainer,
      border: AppColorsDark.border,
      danger: AppColorsDark.danger,
      shadowColor: AppColorsDark.shadow,
    );
  }

  static ThemeData _build({
    required Color backgroundColor,
    required Color surface,
    required Color surfaceTint,
    required Color textPrimary,
    required Color textMuted,
    required Color onPrimary,
    required Color primary,
    required Color primaryPressed,
    required Color primaryContainer,
    required Color onPrimaryContainer,
    required Color water,
    required Color waterContainer,
    required Color border,
    required Color danger,
    required Color shadowColor,
  }) {
    final ColorScheme scheme = ColorScheme(
      brightness: backgroundColor == AppColorsDark.background
          ? Brightness.dark
          : Brightness.light,
      primary: primary,
      onPrimary: onPrimary,
      primaryContainer: primaryContainer,
      onPrimaryContainer: onPrimaryContainer,
      secondary: water,
      onSecondary: backgroundColor == AppColorsDark.background
          ? const Color(0xFF08244A)
          : const Color(0xFFFFFFFF),
      error: danger,
      onError: backgroundColor == AppColorsDark.background
          ? const Color(0xFF7F1D1D)
          : const Color(0xFFFFFFFF),
      surface: surface,
      onSurface: textPrimary,
      outline: border,
      shadow: shadowColor,
    );

    final VisualDensity density = const VisualDensity(vertical: 0.75, horizontal: 0.75);

    return ThemeData(
      useMaterial3: true,
      brightness: scheme.brightness,
      colorScheme: scheme,
      scaffoldBackgroundColor: backgroundColor,
      textTheme: buildCairoTextTheme(
        textPrimary: textPrimary,
        textMuted: textMuted,
      ),
      visualDensity: density,
      splashFactory: InkRipple.splashFactory,
      dividerTheme: DividerThemeData(color: border, thickness: 1),
      iconTheme: IconThemeData(color: textPrimary, size: AppIcon.action),
      appBarTheme: AppBarTheme(
        backgroundColor: backgroundColor,
        foregroundColor: textPrimary,
        elevation: AppElevation.none,
        centerTitle: true,
        titleTextStyle: TextStyle(
          fontFamily: AppFont.family,
          fontSize: AppTypeScale.titleSection,
          fontWeight: AppWeights.bold,
          color: textPrimary,
        ),
      ),
      cardTheme: CardTheme(
        color: surface,
        elevation: AppElevation.card,
        shadowColor: shadowColor,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.card),
          side: BorderSide(color: border),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: primary,
          foregroundColor: onPrimary,
          disabledBackgroundColor: primaryContainer,
          disabledForegroundColor: textMuted,
          minimumSize: const Size(0, AppTarget.minButtonHeight),
          textStyle: TextStyle(
            fontFamily: AppFont.family,
            fontSize: AppTypeScale.label,
            fontWeight: AppWeights.bold,
          ),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadius.button),
          ),
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: primaryPressed,
          textStyle: TextStyle(
            fontFamily: AppFont.family,
            fontSize: AppTypeScale.label,
            fontWeight: AppWeights.semiBold,
          ),
        ),
      ),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: textPrimary,
        contentTextStyle: TextStyle(
          fontFamily: AppFont.family,
          fontSize: AppTypeScale.bodySmall,
          color: backgroundColor,
        ),
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.button),
        ),
      ),
    );
  }
}
