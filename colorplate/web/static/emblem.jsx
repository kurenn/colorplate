/* emblem.jsx — filament presets, color math, and the concentric brand mark.

   Detection of real regions now happens on the server; the Emblem here is used
   only as the small brand logomark in the top bar (painted with the current
   assigned filaments when a file is loaded, or a fixed palette otherwise). The
   color helpers mirror the Python service so the custom-hex picker names colors
   identically. */

// Built-in filament presets (exactly the spec list)
const PRESETS = [
  { name: "Red",        hex: "#D11A2A" },
  { name: "White",      hex: "#F4F4F4" },
  { name: "Black",      hex: "#101010" },
  { name: "Charcoal",   hex: "#231F1D" },
  { name: "Gold",       hex: "#F9CF26" },
  { name: "Orange-Red", hex: "#ED4324" },
  { name: "Yellow",     hex: "#FBD732" },
  { name: "Teal",       hex: "#A8DFDF" },
];

function hexToRgb(h) {
  const x = h.replace("#", "");
  const v = x.length === 3 ? x.split("").map((c) => c + c).join("") : x;
  return [parseInt(v.slice(0, 2), 16), parseInt(v.slice(2, 4), 16), parseInt(v.slice(4, 6), 16)];
}
function luminance(hex) {
  const [r, g, b] = hexToRgb(hex).map((c) => c / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
// perceptual-ish weighted distance for nearest-preset matching ("redmean")
function colorDist(a, b) {
  const [r1, g1, b1] = hexToRgb(a), [r2, g2, b2] = hexToRgb(b);
  const rm = (r1 + r2) / 2;
  const dr = r1 - r2, dg = g1 - g2, db = b1 - b2;
  return Math.sqrt((2 + rm / 256) * dr * dr + 4 * dg * dg + (2 + (255 - rm) / 256) * db * db);
}
function nearestPreset(hex) {
  let best = PRESETS[0], bd = Infinity;
  for (const p of PRESETS) {
    const d = colorDist(hex, p.hex);
    if (d < bd) { bd = d; best = p; }
  }
  return { ...best };
}
function slug(name) { return name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, ""); }
function isLight(hex) { return luminance(hex) > 0.62; }

// Fixed palette for the top-bar mark before any file is loaded.
const BRAND_REGIONS = [
  { id: "T1", filament: { name: "Charcoal", hex: "#231F1D" } },
  { id: "T2", filament: { name: "Gold", hex: "#F9CF26" } },
  { id: "T3", filament: { name: "Red", hex: "#D11A2A" } },
  { id: "T4", filament: { name: "White", hex: "#F4F4F4" } },
];

/* Concentric, slightly-offset "loft" plates: 6 nested discs grouped into N
   regions, painted with each region's assigned filament hex. */
const DISCS = [
  { r: 96, dx: 0,   dy: 0 },
  { r: 80, dx: 3,   dy: -5 },
  { r: 63, dx: 6,   dy: -10 },
  { r: 47, dx: 9,   dy: -14 },
  { r: 31, dx: 12,  dy: -17 },
  { r: 15, dx: 14,  dy: -19 },
];

function Emblem({ regions, size = 300 }) {
  const regs = regions && regions.length ? regions : BRAND_REGIONS;
  const n = regs.length;
  const cx = 110, cy = 116;
  const regionForDisc = (i) => Math.min(n - 1, Math.floor((i * n) / DISCS.length));
  return (
    <svg className="emblem-box" width={size} height={size} viewBox="0 0 220 232" role="img" aria-label="logo preview">
      <defs>
        <clipPath id="ecircle"><circle cx={cx} cy={cy} r="100" /></clipPath>
      </defs>
      <g clipPath="url(#ecircle)">
        {DISCS.map((d, i) => {
          const reg = regs[regionForDisc(i)];
          return (
            <circle key={i} cx={cx + d.dx} cy={cy + d.dy} r={d.r}
                    fill={reg.filament.hex}
                    stroke="var(--bg)" strokeWidth={i === 0 ? 0 : 2.4} />
          );
        })}
      </g>
      <circle cx={cx} cy={cy} r="100" fill="none"
              stroke="color-mix(in oklab, var(--text) 12%, transparent)" strokeWidth="1.5" />
    </svg>
  );
}

Object.assign(window, {
  PRESETS, hexToRgb, luminance, colorDist, nearestPreset, slug, isLight,
  BRAND_REGIONS, Emblem,
});
