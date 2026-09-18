/** Minimal class-name joiner. Keeps a dependency out of the tree for something this small. */
export function cn(...values: (string | false | null | undefined)[]): string {
  return values.filter(Boolean).join(" ");
}
