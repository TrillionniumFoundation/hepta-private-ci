#!/usr/bin/env python3
"""Post-patch hardening for the one-shot runtime.codex convergence bootstrap."""

from __future__ import annotations

import json
from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, found {count}: {old[:100]!r}")
    write(path, content.replace(old, new, 1))


def create(path: str, content: str) -> None:
    target = ROOT / path
    if target.exists():
        raise SystemExit(f"refusing to overwrite {path}")
    write(path, textwrap.dedent(content).lstrip())


# Test-only synchronization imports must not trip strict production lint.
replace_once(
    "codex-rs/hepta-infer-worker-host/src/runtime_codex_state.rs",
    "use std::sync::Mutex;\nuse std::sync::OnceLock;\n",
    "#[cfg(test)]\nuse std::sync::Mutex;\n#[cfg(test)]\nuse std::sync::OnceLock;\n",
)

# The handoff is already generation-fenced by AgentdClient; the handoff type
# intentionally carries no independently mutable generation field.
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "            || aborted.generation != binding.generation\n",
    "",
)

# Make lifecycle metrics an externally observable diagnostics surface rather
# than private dead code.
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''#[path = "runtime_codex_thread.rs"]
mod runtime_codex_thread;
''',
    '''#[path = "runtime_codex_thread.rs"]
mod runtime_codex_thread;
pub use runtime_codex_thread::RuntimeCodexThreadMetrics;
pub use runtime_codex_thread::runtime_codex_thread_metrics;
''',
)

# Production file-based configuration must pin the actual Linux process
# instance. Tests may still construct an in-process issuer explicitly.
replace_once(
    "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs",
    '''        let config: FinalUseAuthorizerConfig =
            serde_json::from_slice(&read_private_config(config_path)?)?;
        Self::from_config(config)
''',
    '''        let config: FinalUseAuthorizerConfig =
            serde_json::from_slice(&read_private_config(config_path)?)?;
        #[cfg(target_os = "linux")]
        if config.issuer_process.is_none() {
            return Err(
                "production final-use authority config must pin issuer PID, executable and start time"
                    .into(),
            );
        }
        Self::from_config(config)
''',
)

# Avoid unrelated dependency lints obscuring the dedicated owner boundary.
workflow_path = ".github/workflows/runtime-codex-required.yml"
workflow = read(workflow_path)
workflow = workflow.replace(
    "cargo clippy --locked --all-targets \\\n",
    "cargo clippy --locked --all-targets --no-deps \\\n",
)
workflow = workflow.replace(
    "cargo clippy --manifest-path codex-rs/Cargo.toml --locked --all-targets \\\n",
    "cargo clippy --manifest-path codex-rs/Cargo.toml --locked --all-targets --no-deps \\\n",
)
if "--no-deps" not in workflow:
    raise SystemExit("failed to scope runtime.codex lint")

performance_step = '''      - name: Measure repository product baseline
        shell: bash
        run: |
          set -euo pipefail
          python3 scripts/hepta-runtime-codex-benchmark.py \\
            --iterations 5 \\
            --output .hepta-evidence/runtime-codex/performance.json \\
            -- bash -lc 'cd codex-rs && cargo test --locked -p codex-hepta-agentd --test runtime_codex_product_e2e -- --test-threads=1'

'''
marker = "      - name: Concurrency and restart stress\n"
if workflow.count(marker) != 1:
    raise SystemExit("could not insert runtime.codex performance measurement")
workflow = workflow.replace(marker, performance_step + marker, 1)

attestation = '''      - name: Attest synthetic-merge receipt
        if: github.event_name == 'push'
        uses: actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8
        with:
          subject-path: .hepta-evidence/runtime-codex/synthetic-merge.json

'''
marker = "\n  required:\n"
if workflow.count(marker) != 1:
    raise SystemExit("could not insert synthetic-merge attestation")
workflow = workflow.replace(marker, "\n" + attestation + "  required:\n", 1)
write(workflow_path, workflow)

create(
    "scripts/hepta-runtime-codex-benchmark.py",
    r'''
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import time


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("empty sample")
    rank = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[rank]


def parse_max_rss(stderr: str) -> int:
    prefix = "Maximum resident set size (kbytes):"
    for line in stderr.splitlines():
        if prefix in line:
            return int(line.split(":", 1)[1].strip())
    raise ValueError("/usr/bin/time did not report maximum RSS")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if args.iterations < 3 or args.iterations > 32 or not command:
        raise SystemExit("iterations must be 3..=32 and a command is required")

    durations: list[float] = []
    rss: list[int] = []
    for iteration in range(args.iterations):
        started = time.perf_counter()
        completed = subprocess.run(
            ["/usr/bin/time", "-v", *command],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if completed.returncode != 0:
            sys.stdout.write(completed.stdout)
            sys.stderr.write(completed.stderr)
            raise SystemExit(
                f"runtime.codex benchmark iteration {iteration + 1} failed with {completed.returncode}"
            )
        durations.append(elapsed_ms)
        rss.append(parse_max_rss(completed.stderr))

    result = {
        "schema": "hepta.runtime-codex.performance.v1",
        "iterations": args.iterations,
        "command": command,
        "durationMs": {
            "samples": [round(value, 3) for value in durations],
            "p50": round(percentile(durations, 0.50), 3),
            "p95": round(percentile(durations, 0.95), 3),
            "p99": round(percentile(durations, 0.99), 3),
            "maximum": round(max(durations), 3),
        },
        "maxRssKiB": {
            "samples": rss,
            "p95": int(percentile([float(value) for value in rss], 0.95)),
            "p99": int(percentile([float(value) for value in rss], 0.99)),
            "maximum": max(rss),
        },
        "scope": "repository mock-provider composition; not target-host SLO evidence",
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
''',
)

# Bind an available repository baseline into the qualification receipt without
# representing it as a production SLO.
evidence_path = "scripts/hepta-runtime-codex-evidence.py"
evidence = read(evidence_path)
replace = '''    performance_path = ROOT / ".hepta-evidence" / "runtime-codex" / "performance.json"
    if performance_path.exists():
        document["repositoryPerformance"] = json.loads(
            performance_path.read_text(encoding="utf-8")
        )
'''
needle = "    output = ROOT / args.output\n"
if evidence.count(needle) != 1:
    raise SystemExit("could not bind performance evidence")
evidence = evidence.replace(needle, replace + "\n" + needle, 1)
needle = '    "docs/modules/runtime.codex/QUARANTINE_PROTOCOL.md",\n'
if evidence.count(needle) != 1:
    raise SystemExit("could not extend evidence source inventory")
evidence = evidence.replace(
    needle,
    needle
    + '    "docs/modules/runtime.codex/CANARY_ROLLBACK.md",\n'
    + '    "docs/modules/runtime.codex/TARGET_HOST_PROFILE.schema.json",\n'
    + '    "scripts/hepta-runtime-codex-benchmark.py",\n',
    1,
)
write(evidence_path, evidence)

create(
    "docs/modules/runtime.codex/CANARY_ROLLBACK.md",
    r'''
# runtime.codex canary and rollback contract

Repository CI cannot authorize deployment.  An independent release owner may
start a canary only after exact-head, synthetic-merge and target-host receipts
are current and signed.  The canary begins with zero external tools and a
bounded model-only cohort.  Admission closes automatically on issuer/process
identity drift, revocation rollback, trusted-clock failure, provider-terminal
loss, cleanup saturation, duplicate effects, or any unresolved quarantine
above the selected host threshold.

Rollback stops new admission first, preserves every durable operation, restores
a binary and schema-compatible state set, and reconciles already-entered
effects before capacity is released.  A rollback must never restore an older
authority epoch or revocation frontier.  Promotion and release remain separate,
independently signed decisions; repository receipts always retain `release:
false`.
''',
)

create(
    "docs/modules/runtime.codex/TARGET_HOST_PROFILE.schema.json",
    r'''
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://hepta.example/schemas/runtime-codex-target-host-profile-v1.json",
  "title": "runtime.codex target-host qualification profile",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema",
    "sourceSha",
    "sourceTree",
    "hostIdentity",
    "agentd",
    "appServer",
    "issuer",
    "provider",
    "trustedTime",
    "faultCampaign",
    "performance",
    "independentSigner"
  ],
  "properties": {
    "schema": { "const": "hepta.runtime-codex.target-host.v1" },
    "sourceSha": { "type": "string", "pattern": "^[0-9a-f]{40}$" },
    "sourceTree": { "type": "string", "pattern": "^[0-9a-f]{40}$" },
    "hostIdentity": { "type": "object" },
    "agentd": { "type": "object" },
    "appServer": { "type": "object" },
    "issuer": {
      "type": "object",
      "required": ["uid", "pid", "executable", "startTimeTicks", "signerKeyDigest", "authorityEpoch", "revocationRevision"]
    },
    "provider": { "type": "object" },
    "trustedTime": { "type": "object" },
    "faultCampaign": { "type": "object" },
    "performance": {
      "type": "object",
      "required": ["p50Ms", "p95Ms", "p99Ms", "maxRssKiB"]
    },
    "independentSigner": { "type": "object" }
  }
}
''',
)

technical = read("docs/modules/runtime.codex/TECHNICAL.md")
section = r'''

## 17. Correctness-convergence and qualification surfaces

The exact `run_abort_before_effect` transition closes both Agentd and the local
durable owner only while the live one-shot proof establishes that no physical
`turn/start` was entered.  Ambiguous Agentd acknowledgement remains
reconcile-only.  The checked runtime state machine, lifecycle metrics and crash
checkpoints are described in [FAULT_INJECTION_MATRIX.md](FAULT_INJECTION_MATRIX.md).

Independent history-loss handling follows
[QUARANTINE_PROTOCOL.md](QUARANTINE_PROTOCOL.md).  Developer, deployment,
operations, target-host and canary procedures are in [QUICKSTART.md](QUICKSTART.md),
[DEPLOYMENT.md](DEPLOYMENT.md), [OPERATIONS.md](OPERATIONS.md),
[TARGET_HOST_QUALIFICATION.md](TARGET_HOST_QUALIFICATION.md), and
[CANARY_ROLLBACK.md](CANARY_ROLLBACK.md).  The reusable
`runtime.codex required qualification` workflow emits exact-head and ordered
synthetic-merge machine-readable receipts.  Push receipts receive GitHub OIDC
provenance attestations; no repository receipt self-certifies target-host
acceptance, promotion or release.
'''
if "## 17. Correctness-convergence and qualification surfaces" in technical:
    raise SystemExit("technical convergence section already exists")
write("docs/modules/runtime.codex/TECHNICAL.md", technical.rstrip() + section + "\n")

implementation_map_path = "docs/modules/runtime.codex/IMPLEMENTATION_MAP.json"
implementation_map = json.loads(read(implementation_map_path))
implementation_map["performanceBaseline"] = {
    "emitter": "scripts/hepta-runtime-codex-benchmark.py",
    "scope": "repository mock-provider composition only",
    "targetHostSloComplete": False,
}
implementation_map["canaryRollbackContract"] = "docs/modules/runtime.codex/CANARY_ROLLBACK.md"
implementation_map["targetHostProfileSchema"] = (
    "docs/modules/runtime.codex/TARGET_HOST_PROFILE.schema.json"
)
write(implementation_map_path, json.dumps(implementation_map, indent=2) + "\n")

# The post-patch helper is also one-shot.
Path(__file__).unlink()
