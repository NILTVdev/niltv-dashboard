// NIL TV dashboard colors. className colors use the CSS vars in globals.css
// (--brand / --brand-light / --brand-pale); recharts props can't resolve CSS
// vars (SVG presentation attributes), so chart components read these hexes.

export const COLORS = {
  brand: "#101014",      // primary: nav, KPI numbers, main chart series
  brandLight: "#b4975a", // brass-gold accent: second chart series, hovers
  brandPale: "#f6f2e9",  // tinted background chips/pills
};
