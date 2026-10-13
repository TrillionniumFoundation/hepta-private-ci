# Exact-SHA CI evidence gate — shadow qualification, not release approval

The 2026-10-12 native Worker and signed Final-use PRs passed their *scoped*
Rust/Python/architecture checks but were blocked by **whole-repository CI**.
A green result on an earlier branch commit is not transferable to a new
composition, and a successful specialized workflow is not a production NDU,
Stem Artifact CAS, model-weight or crash-recovery acceptance.

`exact_sha_ci_gate.py` is a **read-only fail-closed auditor**. It requires
successful, completed GitHub pull-request runs for exactly the supplied
40-character SHA under all five canonical workflow names, plus their
individual Job records. It requires a concrete successful
`cargo-deny / cargo-deny` Job in the successful `blocking-ci` run.
It rejects a missing workflow, a newer failed attempt, stale/branch-push runs,
cancelled or unfinished Jobs, duplicate Jobs, missing paginated results, or
an absent / skipped cargo-deny. Missing evidence does not become a default.

The resulting JSON explicitly sets:
- `production_promotion_permitted: false`
- `independent_signed_final_use_verified: false`
- `real_jina_weights_executed: false`
- `target_host_4096_cell_qualified: false`
- `source_artifact_CAS_recovery_verified: false`

This auditor does **not** authenticate the GitHub REST JSON; for production a
trusted verifier must additionally bind protected CI provenance, the final
merge result, artifact signatures, owner authorization and signed receipts.

## Collect the actual completed results

Run from a workstation **authorized to access the private GitHub repository**
after the exact final combination commit has been pushed and its CI concludes:

```bash
set -euo pipefail
REPO=TrillionniumFoundation/hepta-private-ci
HEAD_SHA=REPLACE_WITH_EXACT_LOWERCASE_40_HEX_SHA
mkdir -p evidence/jobs
gh api "repos/$REPO/actions/runs?head_sha=$HEAD_SHA&per_page=100" > evidence/runs.json
jq -r '.workflow_runs[] | select(.event=="pull_request") | .id' evidence/runs.json |
  while IFS= read -r run_id; do
    gh api "repos/$REPO/actions/runs/$run_id/jobs?per_page=100" > "evidence/jobs/$run_id.json"
  done
python3 - <<'PY'
from pathlib import Path
import json
files = sorted(Path("evidence/jobs").glob("*.json"))
data = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in files}
Path("evidence/jobs.json").write_text(json.dumps(data), encoding="utf-8")
PY
python3 qualification/neuron-stem/exact_sha_ci_gate.py \
  --head-sha "$HEAD_SHA" \
  --runs-json evidence/runs.json \
  --jobs-json evidence/jobs.json \
  --output evidence/exact-head-shadow-ci.json
```

If either GitHub API reports `total_count` larger than the collected array,
page through all results and combine them before checking; the program
**refuses incomplete pagination**. No successful report from a different SHA
should ever be copied to this output. Refuse to overwrite prior reports, and
retain source payload hashes for later operator audits.

Offline contract tests need no GitHub credentials, Rust binary, downloaded
Jina weights or network:

```bash
PYTHONPATH=qualification/neuron-stem \
  python3 -m unittest discover -s qualification/neuron-stem \
  -p 'test_exact_sha_ci_gate.py' -v
```

## Current blockers (observed 2026-10-13, prior exact check runs)

The 2026-10-12 full-repository checks on Worker PR #1510
(commit `821687a48d245de64f8a0b07339c3bb493a966e8`) and signed
Final-use PR #1517 (commit
`f4cedf984a3e117982a072a1fd9f0d399a071498`)
reported failed `blocking-ci`. Their specialized Neuron Stem / Worker /
architecture / Canary workflows passed, but full-repo promotion is **DENIED**.

- **RUSTSEC-2026-0318**: `matrix-sdk-crypto 0.18.0` vulnerable; fixed
  in 0.19.0 and later.
- **RUSTSEC-2026-0319**: the Matrix SDK's `anymap2 0.13.0` is unmaintained.
  Even `matrix-sdk 0.19.1` retains `anymap2`. No safe cargo-only upgrade
  removes this advisory.
- **RUSTSEC-2024-0449**: deprecated `serde_yaml` depends on archived
  `unsafe-libyaml`. The full parser call surface and locked dependency graph
  need a tested safe-parser migration.
- The published `matrix-sdk 0.19.1` declares **rust-version 1.96**;
  the existing dedicated Hepta CI profile uses **Rust 1.95**. Simply changing
  the SDK version cannot produce a working locked build; perform an explicit
  compiler/toolchain/Bazel migration and an approved compatible SDK upgrade.
- Windows Bazel had build/test failures on those prior runs. Later upstream
  source contains fixes that must be verified on its **own final SHA**, not
  treated as implicit success.

References for operator verification:
- https://rustsec.org/advisories/RUSTSEC-2026-0318.html
- https://rustsec.org/advisories/RUSTSEC-2026-0319.html
- https://rustsec.org/advisories/RUSTSEC-2024-0449.html
- https://docs.rs/crate/matrix-sdk/0.19.1/source/Cargo.toml
- https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38239518519

Do **not** add advisory ignores, turn off `cargo-deny`, skip failing Windows
tests, or infer native throughput from synthetic NumPy/SQLite probes. Neither
this evidence gate nor a future green Cargo build authorizes a selected Cell,
model CAS load, signed final-use, generation fence, NDU learning outcome or
release.
