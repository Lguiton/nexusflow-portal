#!/usr/bin/env bash
#
# SEC-03: automated dependency vulnerability scanning -- backend (pip-audit)
# and frontend (npm audit), one command, real pass/fail exit code.
#
# Closes the gap the earlier Phase 5 scan (docs/NexusFlow_Phase5_Dependency_
# Security_Scan.md) had to hand off: at that time neither of Claude's own
# execution environments had outbound network access to PyPI, so pip-audit
# could never actually run there -- only npm audit did. This script is safe
# to run from anywhere that DOES have that access (your own machine, or a
# CI runner once one exists -- see CICD-01, not yet built).
#
# Usage:
#   ./scripts/security_scan.sh
#
# Exit code is non-zero if either scan finds a real vulnerability, so this
# can be wired into a CI gate later without any changes to this script.
#
# Scope, stated plainly: this is DEPENDENCY scanning only -- the other two
# things SEC-03's title names (container image scanning, penetration
# testing) are NOT covered here. Container scanning needs a built image to
# scan against (see docker/); pentest tooling and SAST tool choice were
# both explicitly left as open decisions in the Phase 5 doc above rather
# than silently picked -- that boundary is unchanged by this script.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAILED=0

echo "=============================================="
echo " SEC-03 dependency scan -- $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=============================================="

# --- Backend: pip-audit against the real pinned/resolved dependency set ---
echo ""
echo "--- Backend (pip-audit) ---"
if ! command -v pip-audit >/dev/null 2>&1; then
    echo "pip-audit not found -- installing (dev tool only, not a runtime dependency;"
    echo "see backend/requirements-dev.txt)."
    pip install -q -r "$REPO_ROOT/backend/requirements-dev.txt"
fi

if pip-audit -r "$REPO_ROOT/backend/requirements.txt"; then
    echo "Backend: no known vulnerabilities."
else
    echo "Backend: pip-audit found real vulnerabilities (see above) or failed to run -- see exit code."
    FAILED=1
fi

# --- Frontend: npm audit against the full resolved lockfile tree ---
echo ""
echo "--- Frontend (npm audit) ---"
if [ -d "$REPO_ROOT/frontend/node_modules" ]; then
    (cd "$REPO_ROOT/frontend" && npm audit)
    NPM_AUDIT_EXIT=$?
else
    echo "frontend/node_modules not present -- run 'npm install' in frontend/ first, then re-run this script."
    NPM_AUDIT_EXIT=1
fi
if [ "$NPM_AUDIT_EXIT" -ne 0 ]; then
    FAILED=1
fi

echo ""
echo "=============================================="
if [ "$FAILED" -eq 0 ]; then
    echo " RESULT: clean -- no known vulnerabilities in either dependency tree."
else
    echo " RESULT: at least one scan found a real issue or could not run -- see output above."
fi
echo "=============================================="

exit "$FAILED"
