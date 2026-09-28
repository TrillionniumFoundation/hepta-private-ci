#!/usr/bin/env python3
"""Apply the exact browser.servo remediation to one reviewed source base."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BASE = "d1a5c47965be4a1a01ef7753e346b99184d6982b"
ALLOWED_BOOTSTRAP_PATHS = {
    ".github/workflows/hepta-browser-exact-remediation-apply.yml",
    "scripts/hepta_browser_exact_remediation_apply.py",
}


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def require_exact_replacement(path: str, old: str, new: str, count: int = 1) -> None:
    target = ROOT / path
    source = target.read_text()
    if source.count(old) != count:
        raise SystemExit(f"{path}: expected {count} exact anchor(s), found {source.count(old)}")
    target.write_text(source.replace(old, new, count))


def main() -> None:
    if git("merge-base", EXPECTED_BASE, "HEAD") != EXPECTED_BASE:
        raise SystemExit("candidate no longer descends from the reviewed exact base")
    changed = set(filter(None, git("diff", "--name-only", f"{EXPECTED_BASE}...HEAD").splitlines()))
    unexpected = sorted(changed - ALLOWED_BOOTSTRAP_PATHS)
    if unexpected:
        raise SystemExit(f"unexpected pre-remediation changes: {unexpected}")

    require_exact_replacement(
        "codex-rs/hepta-agentd/src/browser_servo_persistent.rs",
        "`FinalUseAuthority::with_verified_use` holds the live revocation",
        "`FinalUseAuthority::with_dispatch_boundary` holds the live revocation",
    )
    require_exact_replacement(
        "codex-rs/hepta-agentd/src/browser_servo_persistent.rs",
        ".with_verified_use(token, &invocation.binding, || {",
        ".with_dispatch_boundary(token, &invocation.binding, || {",
    )

    require_exact_replacement(
        ".github/workflows/hepta-browser-servo-worker-dev.yml",
        """          command -v llvm-objdump
          llvm-objdump --version | head -n 1
          command -v bwrap
          bwrap --version
          command -v prlimit
          prlimit --version | head -n 1
""",
        """          sudo sysctl -w kernel.unprivileged_userns_clone=1
          if sysctl kernel.apparmor_restrict_unprivileged_userns >/dev/null 2>&1; then
            sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
          fi
          command -v llvm-objdump
          llvm-objdump --version | head -n 1
          command -v bwrap
          bwrap --version
          command -v prlimit
          prlimit --version | head -n 1
""",
    )
    require_exact_replacement(
        ".github/workflows/hepta-browser-servo-worker-dev.yml",
        "          node apps/hepta-browser/scripts/linux-sandbox-probe.js | tee worker-evidence/linux-sandbox-probe.json\n",
        """          node apps/hepta-browser/scripts/linux-sandbox-probe.js \\
            2> >(tee worker-evidence/linux-sandbox-probe.stderr.log >&2) \\
            | tee worker-evidence/linux-sandbox-probe.json
""",
    )

    for path in (
        "docs/modules/browser.servo/TECHNICAL.md",
        "qualification/module-execution-dossiers/detail/browser.servo.md",
    ):
        require_exact_replacement(
            path,
            "FinalUseAuthority::with_verified_use",
            "FinalUseAuthority::with_dispatch_boundary",
        )

    require_exact_replacement(
        "docs/modules/browser.servo/IMPLEMENTATION_MAP.json",
        '"symbol": "with_verified_use"',
        '"symbol": "with_dispatch_boundary"',
    )

    remediation = ROOT / "docs/modules/browser.servo/REMEDIATION_20260927.md"
    source = remediation.read_text()
    heading = "## 2026-09-28 exact-head native follow-up"
    if heading in source:
        raise SystemExit("exact-head remediation ledger entry already exists")
    source += """

## 2026-09-28 exact-head native follow-up

The exact candidate `d1a5c47965be4a1a01ef7753e346b99184d6982b`
produced two actionable native diagnostics. They are retained as failures and
are not relabelled as passes.

The Agentd Browser service tests showed that revocation updates could commit
before the worker emitted its dispatch or proven-rejection boundary. The
persistent port was still calling `FinalUseAuthority::with_verified_use`, whose
contract releases the owner mutex before executing the callback. The port now
uses `FinalUseAuthority::with_dispatch_boundary`, so the bounded callback that
sends `authority_enter` and waits for exactly one worker admission/rejection
receipt runs under the live revocation linearization fence. Remote execution
and terminal reconciliation remain outside that fence. The implementation map
and human technical documents bind the same API.

The standalone Linux sandbox diagnostic passed after explicitly enabling the
Ubuntu runner's unprivileged user namespace and disabling the AppArmor
restriction when that sysctl exists. The primary worker workflow previously
installed Bubblewrap without applying those host prerequisites. It now applies
the same fail-closed prerequisite ceremony and retains bounded sandbox-probe
stderr in the worker evidence directory on failure. No failed probe is inferred
to have passed.

The temporary branch-only diagnostic workflow used to isolate these failures
is removed from the candidate after transferring its proven prerequisites and
diagnostics into the canonical Agentd and worker workflows. It is not retained
as a parallel qualification or release path.

A fresh exact-head and deterministic-merge execution remains mandatory. The
repository-controlled source boundary, production implementation, product
execution, deployment qualification, operator acceptance, activation,
promotion and release booleans remain false until their designated terminal
evidence exists.
"""
    remediation.write_text(source)


if __name__ == "__main__":
    main()
