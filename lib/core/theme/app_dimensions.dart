// Named sizes and touch targets used across the app so a single source of
// truth drives both the text theme and widget-level emphasis styles.

/// Raw scale results referenced by widgets individually — keep the theme
/// tokens and these constants in sync.

class AppTypeScale {
  static const double titlePage = 34.0; // screen headlines
  static const double titleSection = 26.0; // card headings / medicine names
  static const double titleItem = 24.0;
  static const double timeLarge = 28.0; // dose times
  static const double body = 22.0; // primary reading text
  static const double bodySmall = 20.0; // absolute min for body text
  static const double label = 20.0; // big button labels
  static const double caption = 18.0; // helper text only
}

class AppWeights {
  static const FontWeight regular = FontWeight.w400;
  static const FontWeight medium = FontWeight.w500;
  static const FontWeight semiBold = FontWeight.w600;
  static const FontWeight bold = FontWeight.w700; // medicine names / times
}

class AppFont {
  static const String family = 'Cairo';
}

/// Physical spacing / sizing in logical pixels.

class AppSpacing {
  static const double xxs = 4.0;
  static const double xs = 8.0;
  static const double sm = 12.0;
  static const double md = 16.0;
  static const double lg = 24.0;
  static const double xl = 32.0;
  static const double xxl = 40.0;
}

/// Elderly touch-target rules — never shrink these.

class AppTarget {
  static const double minButtonHeight = 64.0; // secondary/quick actions
  static const double heroConfirmHeight = 80.0; // "أخذت الدواء"
  static const double navBarHeight = 76.0; // includes label
  static const double minTapEdge = 48.0; // any interactive chrome
}

class AppRadius {
  static const double card = 24.0;
  static const double button = 20.0;
  static const double pill = 999.0;
  static const double progress = 8.0;
}

class AppIcon {
  static const double nav = 30.0; // bottom nav icons
  static const double action = 28.0; // inside buttons / rows
  static const double accent = 40.0; // water cup, med icon
}

class AppElevation {
  static const double none = 0.0;
  static const double card = 3.0;
}
