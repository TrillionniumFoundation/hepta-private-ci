# Execution06 postseal review entrypoints

These are prospective entrypoints and unfilled static contracts. Their existence is not a completion receipt. Preparation and tests use source/metadata and synthetic fixtures only. No scientific value is filled into the templates, no scientific task is started, and no original RAW, source or seal is rewritten.

## 1. Initial registration, before any new endpoint barrier

The root initializer calls:

```python
from operational.parameter_field_recovery06.postseal.prepare_plan import build_plan
plan = build_plan(producer_config_descriptor, source_commit)
```

It seals the returned dictionary as `fullstudy_execution06_ops/registrations/initial/PRE_ENDPOINT_PLAN06.json`, records its exact descriptor in the initial metadata, and preserves the original `PRE_ENDPOINT_PLAN.json` descriptor as `original_plan`.

The five new Python files and three static contracts are checked against the registered source commit. The original plan's complete `analyses`, constraints, diagnostic source pins, protocol and metrics must remain identical. Only execution06 source, producer, roots, registration time and provenance are adapted. FIELD_MAP and C_SCOPE retain exact descriptors of their original execution05 contracts; their new episode/source/cost metadata is explicit, while scientific definitions and interpretations remain unchanged. `build_plan` performs no writes and rejects an existing execution06 endpoint/aggregate barrier. The source closure includes these Python files before the initializer creates its earlier A/C freezes; the later plan itself is not inserted into those freezes, avoiding a hash cycle.

## 2. Wait for real primary closure

Required conditions are actual execution06 primary completion, exit-zero execution06 outer wait4, all14 logical jobs with explicit imported A17 and13 freshly executed jobs, all26/30 declared seals, `evidence_v2/verification06`, and17 actual ordered durable ACKs covering the final logical manifest. Import provenance additionally retains the original execution04 A17 closure. A FAILED marker blocks completed interpretation. The exact detached startup/return chain is also required: INTENT, FORKED, READY, BRIDGE_WAIT4, ACCEPTED, TARGET_STARTED and DAEMON_RETURNED must agree with the actual final outer wait4 identity/configuration/source. The measuring parent must have been adopted by PID1 before science. Its recorded FD closure is required. A bootstrap or daemon failure blocks admission. READY, ACCEPTED and bridge wait4 are never substitutes for final supervisor wait4, and a departed daemon is not required to remain live during this terminal metadata check.

The preparer hashes aggregate result bytes without decoding them. It checks ACK/ACK_VERIFIED, request, archive manifest and verification metadata. It does not reopen retired duplicate binary readback paths and does not rerun archive restoration. No remote authentication or upload is silently repeated.

Run this fixed entry through the unchanged measured `operational/parameter_field_recovery04/external_step.py`, using a new directory `fullstudy_execution06_ops/root_steps/postseal_prepare_pins_01` and execution06's `empty_cwd`:

```text
VERIFIED_VENV_PYTHON -B SOURCE/operational/parameter_field_recovery06/postseal/prepare_pins.py
  --pipeline-config OPS/registrations/initial/PIPELINE_CONFIG.json
  --expected-config-sha256 ACTUAL_EXTERNALLY_FROZEN_CONFIG_SHA256
  --plan OPS/registrations/initial/PRE_ENDPOINT_PLAN06.json
  --expected-plan-sha256 ACTUAL_INITIAL_PLAN_SHA256
  --execute
```

`SOURCE` is `/workspace/scratch/178ced6a501f/fullstudy_recovery06_git`; `OPS` is `/workspace/scratch/178ced6a501f/fullstudy_execution06_ops`. The verified interpreter is `/workspace/scratch/178ced6a501f/runtime_recovery_20261030/venv/bin/python`. SHA arguments must be the real externally selected initialization pins, never guessed future values.

Only after metadata passes does the preparer create the fresh workspace `/workspace/scratch/178ced6a501f/fullstudy_execution06_postseal_20261030/control`, with `PRIMARY_ACK_AUDIT.json` and `POSTSEAL_ARGUMENTS.json`. Existing output is a reconciliation condition, not an automatic retry opportunity.

## 3. Execute the exact prepared supplement argv once

Read the actual `control/POSTSEAL_ARGUMENTS.json` and pass its entire `argv` list directly as the child argv to the original `external_step.py`, with directory `OPS/root_steps/postseal_supplement_01`, cwd `OPS/empty_cwd`, and **no stdin forwarding**. Do not replace that measured argv with an intermediate launcher, because review checks the actual intent against the prepared argv.

The prepared command enters `run_supplement.py`, which validates the prospective plan and producer config, then invokes the original frozen supplement in `ProducerAdapter.for_postseal`. There is no training, scoring, checkpoint restore, refit, bootstrap or new analysis family. The original supplement admits scientific payloads only after its actual whole-study metadata/source/seal gate.

Exit0 means the finite descriptive supplement is complete without reported integrity issues. Exit3 retains the complete supplement with explicit issues and blocks unqualified scientific interpretation. Exit2 is blocked/failed. The original supplement and the primary analysis are never automatically rerun.

## 4. Produce the actual five-priority review

After the supplement's measured helper has exited and written its real WAIT4, invoke `review.py` through the same frozen measuring wrapper, with new directory `OPS/root_steps/postseal_review_01` and the same empty cwd:

```text
VERIFIED_VENV_PYTHON -B SOURCE/operational/parameter_field_recovery06/postseal/review.py
  --arguments WORK/control/POSTSEAL_ARGUMENTS.json
  --expected-arguments-sha256 ACTUAL_ARGUMENT_RECEIPT_SHA256
  --wait4 OPS/root_steps/postseal_supplement_01/WAIT4.json
  --expected-wait4-sha256 ACTUAL_SUPPLEMENT_WAIT4_SHA256
  --execute-review
```

`WORK` is `/workspace/scratch/178ced6a501f/fullstudy_execution06_postseal_20261030`. Obtain both SHA values from the actual closed, selected receipts. The review accepts supplement exit3 only when its COMPLETE, issues, gate and measured intent all agree. It re-enters the original **metadata-only** producer-aware postseal gate; it does not execute supplement calculations again. Only afterward does it decode the already sealed aggregate and descriptive outputs.

Successful review creates a fresh `WORK/review` directory:

| File | Meaning |
| --- | --- |
| `A_INACTIVE_GLOBAL.json` | Original exact12field-path/72decision predicate, using original PATHS traces and aggregate cross-checks. |
| `REVIEW.json` | Complete mapping of existing findings, formal contrasts, descriptive diagnostics, costs, interpretation limits and actual provenance. |
| `COMMENTS.zh-CN.md` | Filled comments with all ten B and eight C contrasts, both observers, original CI directions, per-seed/model effects, scope and cost explanations. |
| `COMPLETE.json` | Review completion and output identities; no automatic scientific benefit or remote-persistence claim. |

A review with integrity issues exits3 and marks `unqualified_interpretation_blocked`. All original statistical booleans remain unchanged. Missing output, omitted family member, false scope, altered provenance or incomplete population causes refusal; no replacement result is fabricated.

## Mandatory scientific interpretation limits

- **P1:** Distinguish action intent, accepted postguard dynamics, parameters/optimizer, semantic output and cost. A/B have macro48 transaction boundaries. C has before/candidate/after whole-state hashes and first whole-state divergence at macro16, plus guard/fallback/work. C does not have per-decision parameter/optimizer hashes/norms or an internal-microstep first-divergence trace. Its component null is unavailable, not evidence of no divergence.
- **P2:** Existing A labels are candidate macro48 plus fixed seed baseline to clock288; C uses macro16/baseline2 to96. These realized matched tails are not expected Q or a uniform certificate. A supplement has108 rows across9heads and36dependent calibration parent slots;0new independent samples. It does not evaluate C's two gated calibration heads. Preserve zero-gain ratios as null/undefined. R's576A terminals and the four prescribed C reconstruction audits have different scopes.
- **P3:** The four-action/guard/fit comparison is field12 versus learned full-current-state and same-observation history. Full-state ridge is not an oracle, and history still pays observation cost. W's three predefined momentum-reflection pairs are near field and constructed off policy. Shared best actions can eliminate forced regret despite a ranking change.
- **P4:** Keep all ten B effects, especially strong ordinary adequacy, fixed-taper minus field, and taper retention, with both observers and fixed-model per-seed values. The original field boolean excludes taper and total-cost Pareto admission. History is not the cheap controller. Preserve recorded offline, deployment, scoring and operational scopes; do not invent a retrospective quality/cost exchange rate.
- **P5:** Keep interaction, both simple effects, dual-field minus ordinary-field and all four own-warmstart retention effects. Positive interaction can mean less harm. The original interaction+retention gate does not require a positive dual simple-effect lower bound; report both without changing the original gate. The controlled FPT event-law treatment is not complete Hepta/NDU or an LLM-scale claim.

The earlier historical gradient lower bound **182,096**, failed execution04 A29 increment **14,784**, and failed execution05 A29 increment **17,280** remain separate; the historical sum is **214,160**. The complete planned logical study **343,808** includes A17 once, so the expected all-attempts lower bound is **557,968**. The review rejects the old subtotal or a duplicated A17 increment. Execution05 optimizer count is **15,984**; truncated trace counters remain a corroborating subset. Execution04 outer CPU contains A17 and is nonadditive to its current stage row. Execution05 actual outer wait4 is missing: controller **1,548.712305 seconds** plus supervisor self interval **7.248885367 seconds** is only a **1,555.961190367-second** measured lower bound. The worker **1,512.719833 seconds** and phase CPU are nested, never added. Execution06 outer excludes historical A17. Full historical CPU remains unknown; archive/recovery engineering and nested supplement intervals retain their separate scopes. Wall time and peak RSS are never summed. The original resource-contract failure and historical V5 FAIL remain visible.

## Terminal preservation and publication

The final primary ACK cannot contain its own later ACK, primary COMPLETE, outer WAIT4, postseal output or review WAIT4. Those belong to a separate actually closed terminal batch. Persist that batch with actual remote identities and independent byte readback, then persist the terminal-closure record itself. No future receipt is required to contain itself. Root owns actual uploads, public-manifest selection and Git publication. This review does not perform them or infer their completion.

## Synthetic verification

`python3 -B -m unittest operational.parameter_field_recovery06.postseal.test_review -v` uses temporary synthetic files, no model or data imports and no real RAW writes. It covers the real17-ACK metadata traversal with deliberately absent retired readback paths; failure/tamper refusal; the original inactive denominator including rejected overrides; pre-endpoint plan drift refusal; exact wrapper args/exit3; completed integrity-issue handling; the108/36 dependency contract; C unavailable diagnostics; both effect families; simple-effect/interaction distinction; one-time A17 accounting; additive failed05 work; full-study lower bound557,968; missing/unknown CPU refusal; and detached return/identity/failure checks.
