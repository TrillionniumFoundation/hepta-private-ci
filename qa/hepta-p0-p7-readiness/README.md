# Hepta Stem→System 2/NDU P0–P7 source-exact CI preflight

**Read-only engineering audit, not scientific acceptance or production authority.**

The repo has many stacked draft research PRs, successful *scoped* workflows and unresolved global/native/security tests. This small stdlib-only tool joins the currently pinned PR commit identity, necessary workflow results and original native job status. It deliberately **never** derives full P0–P7 closure from a test count, source patch, valid hash, self-reported result or green workflow alone. No production activation; `SHADOW_ONLY / DENY_ALL / HOLD_NO_GO`.

## Run

```bash
python3 -m unittest discover -s qa/hepta-p0-p7-readiness -p 'test_*.py' -v
GITHUB_TOKEN="$GITHUB_TOKEN" python3 qa/hepta-p0-p7-readiness/audit.py \
  --plan qa/hepta-p0-p7-readiness/candidate_plan.json \
  --output /tmp/hepta-p0-p7-ci-observation.json
```

`--require-ci-ready` returns exit 2 if any of the eight **CI preflights** fails. Even when all pass, output retains `all_blockers_closed=false`, `model_promotion_authorized=false`, and the immutable externally verifiable science/authority gaps per stage. This tool does not download model weights, execute agents, touch mutable state, or grant tool permissions.

`candidate_plan.json` is a timestamped **2026-10-23 pinned snapshot**, not a list of PRs to merge blindly. Every PR/HEAD change requires reviewing and updating that exact SHA and its owning native workflows. Failure of a deprecated/older source should not be assumed to remain a problem in future integrations; neither should a donor-source green check qualify a new combined source. A branch's PR result is not final **prospective merge** CI or target-device approval.

## Current science and implementation blockers

| Stage | Evidence owner / context | Required external gate still open |
| --- | --- | --- |
| P0 | #2695, #3122, #3222, #3227 | signed real end-to-end Encoder owner forward, generation/source/resource parity and final combined CI |
| P1 | #3110, #3125 | private Cell future/OOD generalization beyond strong frozen retrieval/linear/pooled controls with sufficient coverage |
| P2 | #3122, #3370 | source-disjoint natural audio/video plus modality/pairing dropout evidence and true end-to-end model cost |
| P3 | #2695, #3395 | 8–16 real guided operations with independent step verifier, backtracking and matched search controls |
| P4 | #3213, #3370, #3393, #3416 | preregistered new heldout/multiseed matched cost and risk-covariance **nonzero identifiable control effect** |
| P5 | #3125 | successful independent multi-task NDU trajectory distillation; no negative transfer |
| P6 | #3125, #2988 | three real Split/Merge/Retire snapshots, withdrawal, CAS/rollback and future-window gain |
| P7 | #3227, #3364, #3381, #3396 | physical target p95/p99/RSS/energy, native Windows DELETE isolation, complete latest SHA CI and independent FinalUse |

The original NDU v1 real grounded trial #3213 was negative (0.833594 quality vs best-of-2 0.869010; 3.178649 vs 2.564518 mean seconds). P39 #3122 succeeded narrowly in COCO source caption pairing (251/256 gated, 250/256 interacting linear), not verified natural semantic reasoning. Memory #3125 contains stronger-baseline failures and a tiny student's failure against target-mean. P41 #3227 measured 4096 physically separate copies of fixed Head templates, not 4096 independently acquired skills or entire Encoder cost. P4's #3416 fixes a zero-probability numerical underflow and malformed costs with a successful focused GitHub Actions job, but does not undo these negative experiments.

**Security blocker:** Windows runner #3364 demonstrated restricted-token deletion outside allowed roots using inherited parent `FILE_DELETE_CHILD`. Do not loosen the original denied-outside/allowed-workspace assertions or count a Low-integrity label alone as isolation. The investigation, repair and retest require real Windows execution and independent approval.

## Why an all-PASS synthetic test is still HOLD_NO_GO

Unit tests exercise only tool logic with simulated GitHub API responses. The production check fetches current GitHub PR heads twice (to detect drift), only considers exact-sha `pull_request` workflow runs **associated with the same target PR number and linked PR-head SHA** (a different PR can reuse a commit), selects the newest matching attempt, requires all mandatory native jobs truly completed with `success`, and rejects incomplete pages rather than assuming missing runs passed. It does not verify the external independent origin of task labels, raw decoded outputs, authority signatures or hardware counters. That is why it *cannot* qualify scientific or production evidence alone.

The project owner must explicitly review any prospective combined PR against unmodified security controls, registered scientific protocols, heldout outcome receipts, true cost/energy measurements, and independent authorization before converting any scientific/blocker status to closed.

## Exact-source hosted evidence observer

The scoped workflow uses the already exercised `ubuntu-slim` runner to execute only Python standard-library tests and read-only GitHub API observations. On pull requests it checks out `github.event.pull_request.head.sha` rather than the synthetic merge ref; a workflow dispatch checks out `github.sha`. An explicit `git rev-parse HEAD` equality check must succeed **before** the existing 11 adversarial tests or remote status audit runs. Checkout credentials are not persisted.

The script's pinned candidate plan and all its strict CI/native/scientific requirements remain unchanged. A successful workflow is only proof that this observer was run on the named source, not that any original PR, Windows DELETE isolation, model, future/OOD evaluation, NDU benefit, hardware energy, or FinalUse gate passed. Missing, stale, cancelled, skipped, and failed source evidence remains `BLOCKED`; every P0–P7 capability gate remains `HOLD_NO_GO`.

If the runner is unavailable, source checkout fails, or GitHub API is incomplete, retain the failure/queue evidence. Never replace it with a different branch's PASS or weaker checks.

### Cross-PR run substitution regression

When two open PRs share a commit SHA, GitHub Actions may list their workflows under that same SHA. An unrelated PR's success is **not** qualification evidence for the target PR. The read-only observer now requires each run's actual `pull_requests[].number` and linked `head.sha` to match the pinned PR and SHA. Empty, malformed, missing or aliased associations fail closed; a newer run for another PR cannot override a valid target-specific historical run. Synthetic tests cover these cases; exact-head CI must independently run them.

### Workflow-file identity: duplicate display names

GitHub Actions permits two different YAML files to declare the **same**
`name:` string. A green lightweight workflow from
`.github/workflows/lookalike.yml` must not stand in for a required
`blocking-ci.yml` run even when PR number, source SHA and display name
are identical. The observer now binds approved display names to reviewed
workflow-file paths via `WORKFLOW_PATHS` and filters real GitHub Actions
runs by their exact `path` **before** choosing the most recent run.
Missing paths, unknown workflow names and lookalike paths fail closed.
These file identities are hardcoded in reviewed source instead of being
editable through `candidate_plan.json`. The observer still cannot
establish that the approved workflow file itself is unchanged, or infer
model capability, external science, or production authorization.
