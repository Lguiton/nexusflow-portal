import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import security from "eslint-plugin-security";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // SEC-03 (frontend SAST, 1 Sep 2026): eslint-plugin-security's own
  // recommended config, scoped to source files only -- generated/build
  // output is already excluded below via globalIgnores, and test/e2e
  // files get the same rules applied (deliberately: a real vulnerable
  // pattern in a test fixture is still worth flagging).
  security.configs.recommended,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Stray scratch/leftover directory (old tsc/jest port attempts,
    // pre-existing before this SAST pass) -- not part of the real app,
    // and some of its content is itself a broken/incomplete copy that
    // fails ESLint's own file resolution.
    "_to_delete/**",
  ]),
]);

export default eslintConfig;
