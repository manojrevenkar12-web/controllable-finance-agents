// Values script code needs; the same tokens exist as CSS custom properties in global.css.
export const motionTiming = {
  enter: { duration: 0.2, ease: [0.2, 0.8, 0.2, 1] as const },
  exit: { duration: 0.16 },
  stagger: 0.03,
} as const;

export const layout = { evidenceBar: 96 } as const;
