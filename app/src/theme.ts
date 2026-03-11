export const COLORS = {
  bg:             '#0A0A0F',
  surface:         '#12121A',
  surfaceElevated: '#1A1A26',
  border:          '#1E1E2E',
  borderStrong:   '#2A2740',
  accent:         '#C9A84C',
  accentGlow:     '#E8D5A3',
  accentDim:      '#C9A84C18',
  accentBorder:   '#C9A84C44',
  text:           '#F5F0E8',
  textSecondary:  '#8A8070',
  textTertiary:   '#4A4438',
  success:        '#4CAF7D',
  error:          '#C44B4B',
  // legacy aliases
  muted:          '#8A8070',
};

export const SPACING = {
  xs:    4,
  sm:    8,
  md:    12,
  lg:    16,
  xl:    24,
  xxl:   32,
  xxxl:  48,
  hero:  64,
};

export const RADIUS = {
  sm:   6,
  md:   12,
  lg:   14,
  xl:   20,
  pill: 999,
};

export const FONTS = {
  display: {
    fontFamily: 'Georgia',
    fontStyle:  'italic' as const,
    fontSize:   28,
    color:      '#F5F0E8',
  },
  sub: {
    fontFamily: 'System',
    fontWeight: '600' as const,
    fontSize:   15,
    color:      '#F5F0E8',
  },
  body: {
    fontFamily: 'System',
    fontWeight: '400' as const,
    fontSize:   15,
    color:      '#8A8070',
  },
  label: {
    fontFamily: 'System',
    fontWeight: '600' as const,
    fontSize:   13,
    color:      '#F5F0E8',
  },
  caption: {
    fontFamily: 'System',
    fontWeight: '400' as const,
    fontSize:   12,
    color:      '#4A4438',
  },
  // Legacy aliases — kept for screens not yet migrated
  heading: {
    fontFamily: 'System',
    fontWeight: '700' as const,
    fontSize:   22,
    color:      '#F5F0E8',
  },
  displayLg: {
    fontFamily: 'Georgia',
    fontStyle:  'italic' as const,
    fontSize:   34,
    color:      '#F5F0E8',
  },
  mono: {
    fontFamily: 'Courier New',
    fontSize:   13,
    color:      '#8A8070',
  },
};

// Legacy — kept for screens not yet migrated
export const CARD = {
  backgroundColor: '#12121A',
  borderRadius:    14,
  padding:         16,
  marginBottom:    12,
  borderWidth:     1,
  borderColor:     '#1E1E2E',
};

export const SHADOW = {
  gold: {
    shadowColor:   '#C9A84C',
    shadowOffset:  { width: 0, height: 2 },
    shadowOpacity: 0.25,
    shadowRadius:  8,
    elevation:     4,
  },
};
