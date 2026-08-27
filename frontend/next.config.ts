import path from "path";
import type { NextConfig } from "next";

// Consolidated from next.config.js + next.config.ts, which both existed
// side by side with near-identical content -- Next.js only reads one of a
// duplicate pair (and warns about the ambiguity), so this is now the only
// config file. See frontend/_to_delete/next.config.js for the removed
// duplicate.
const nextConfig: NextConfig = {
  turbopack: {
    // FIXED (real bug, confirmed live 2026-08-26): this used to be a
    // hardcoded absolute path -- "/mnt/c/Users/Guito/eivanta-portal", the
    // project's pre-rebrand folder name/location. The comment above this
    // line used to claim a wrong `root` is "harmless if wrong (falls back
    // to auto-detection)" -- it is NOT: once that folder stopped existing,
    // `next dev` (Turbopack) failed hard with "Error: failed to
    // canonicalize path ... No such file or directory", confirmed live
    // from a real `run-frontend` session. Computed from `__dirname`
    // instead of a hand-typed absolute path so this can never again point
    // at a stale machine-specific location: `frontend/` (where this file
    // lives) is always one directory below the real project root,
    // regardless of what the project folder is named or moved to on any
    // machine.
    root: path.join(__dirname, ".."),
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
