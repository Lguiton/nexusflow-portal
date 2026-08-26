import type { NextConfig } from "next";

// Consolidated from next.config.js + next.config.ts, which both existed
// side by side with near-identical content -- Next.js only reads one of a
// duplicate pair (and warns about the ambiguity), so this is now the only
// config file. See frontend/_to_delete/next.config.js for the removed
// duplicate.
const nextConfig: NextConfig = {
  turbopack: {
    // Silences a lockfile-location warning during local `next dev` --
    // harmless if wrong (falls back to auto-detection), not read at all
    // inside the Docker build (frontend/Dockerfile runs a plain
    // `npx next build`, not Turbopack dev).
    root: "/mnt/c/Users/Guito/eivanta-portal",
  },
  // Required for frontend/Dockerfile's production stage, which copies
  // .next/standalone out of the builder stage (see COPY --from=builder
  // /app/.next/standalone ./). Without this, `next build` never produces
  // that directory and the Docker image build fails at the COPY step --
  // confirmed by reading the Dockerfile; not yet confirmed by an actual
  // `docker build` run (no Docker daemon reachable from either of my
  // sandboxes -- see the Phase 6 report for what's still unverified).
  output: "standalone",
};

export default nextConfig;
