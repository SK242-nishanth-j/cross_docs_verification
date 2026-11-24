import type { Color } from "../types/api";

/** Label shown on a result chip for each colour. */
export const COLOR_LABEL: Record<Color, string> = {
  green: "Match",
  yellow: "Review",
  red: "Mismatch",
  grey: "Not checked",
};
