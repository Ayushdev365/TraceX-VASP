import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pin the workspace root. Without this, Turbopack walks up past the repository and can
  // pick up an unrelated lockfile from the home directory, which makes builds depend on
  // whatever else happens to be on the machine.
  turbopack: {
    root: import.meta.dirname,
  },

  // No image optimization is needed: the dashboard renders graphs and text, not photography.
  images: { unoptimized: true },

  // This is an internal law-enforcement-adjacent tool; it should never be indexed, and it
  // should not advertise its framework.
  poweredByHeader: false,
};

export default nextConfig;
