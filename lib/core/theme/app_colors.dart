// Raw palette values for the elderly-first BrainCare UI.
// Do not use these constants directly inside widgets: resolve roles through
// Theme.of(context).colorScheme so light/dark switching stays automatic.

class AppColorsLight {
  // Backgrounds
  static const Color background = Color(0xFFFFFFFF); // crisp white
  static const Color surface = Color(0xFFFFFFFF);
  static const Color surfaceTint = Color(0xFFF9FAFB); // very subtle panel

  // Text
  static const Color textPrimary = Color(0xFF111827); // charcoal
  static const Color textMuted = Color(0xFF6B7280);
  static const Color onPrimary = Color(0xFFFFFFFF);

  // Actions
  static const Color primary = Color(0xFF16A34A);
  static const Color primaryPressed = Color(0xFF15803D);
  static const Color primaryContainer = Color(0xFFDCFCE7);
  static const Color onPrimaryContainer = Color(0xFF14532D);

  // Water accent
  static const Color water = Color(0xFF2563EB);
  static const Color waterContainer = Color(0xFFDBEAFE);

  // Feedback
  static const Color border = Color(0xFFE5E7EB);
  static const Color danger = Color(0xFFDC2626);

  // Shadows
  static const Color shadow = Color(0x14111827); // 8% charcoal
}

class AppColorsDark {
  // True OLED black background with high-contrast emerald accents.
  static const Color background = Color(0xFF000000);
  static const Color surface = Color(0xFF0F172A);
  static const Color surfaceTint = Color(0xFF111827);

  static const Color textPrimary = Color(0xFFF9FAFB);
  static const Color textMuted = Color(0xFF9CA3AF);
  static const Color onPrimary = Color(0xFF052E16); // near-black on emerald

  static const Color primary = Color(0xFF34D399); // bright emerald
  static const Color primaryPressed = Color(0xFF10B981);
  static const Color primaryContainer = Color(0xFF064E3B);
  static const Color onPrimaryContainer = Color(0xFFA7F3D0);

  static const Color water = Color(0xFF60A5FA);
  static const Color waterContainer = Color(0xFF1E3A8A);

  static const Color border = Color(0xFF1F2937);
  static const Color danger = Color(0xFFF87171);

  static const Color shadow = Color(0x00000000); // none on OLED
}
