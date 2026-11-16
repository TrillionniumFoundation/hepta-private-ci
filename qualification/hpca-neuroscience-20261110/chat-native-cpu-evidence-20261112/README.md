# HPCA public chat-wrapper native CPU diagnostic — 2026-11-12 (HOLD)

**Scope:** one **precommitted, frozen-base** output-format arm on exactly 24 **exposed** tasks. This is an actual native model inference run, not a learned HPCA effect or production qualification.

## Exact source and asset
- Source PR [#6092](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6092), exact HEAD `4669280bd92804e6b5357ec0d8a27197858a5b6a`, Git tree `d78b935a2f5abe1273dced958460c7a3e23ddea6`.
- Source protocol: `CHAT_WRAPPER_PLAN.json` fixed before inference; no prompt search, no new adapters, same 24 public tasks from `HPCA_V2_OOD_PLAN.json`.
- Frozen model: `HuggingFaceTB/SmolLM2-135M-Instruct`, revision `12fd25f77366fa6b3b4b768ec3050bf629380bac`, model.safetensors SHA-256 `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`. Eight actual loaded model assets pinned in PREEXECUTION; existing local bytes reused, no model network download.
- Runtime: authenticated configured `ai395`, Python 3.14.4, torch 2.9.1+cpu, transformers 4.57.3, four inference threads, deterministic greedy, 8 new tokens maximum. Separate frozen venv created in this run; `pip-freeze.txt` and package installation logs archived. No GPU claimed.
- Native run started `2026-11-12T04:45:03.263312+00:00`, finished `2026-11-12T04:45:11.610159+00:00`.

## Actually observed

| Cohort | Parsed YES/NO | Correct on all 24 | First-token EOS |
|---|---:|---:|---:|
| Original **bare prompt** frozen-base diagnostic [#6049](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6049) | 0/24 | 0/24 | 24/24 |
| **New precommitted user chat template** frozen-base native CPU | **12/24** | **6/24** | **0/24** |

The comparison changes only the representation of the input prompt, **not** the model or HPCA mechanism. It diagnoses a format sensitivity of the original EOS collapse; it is **not** evidence for improved HPCA neural computation, training advantage, or a generally reliable generator.

New arm by family: arithmetic valid 1/6 correct 1/6; conditional valid 5/6 correct 2/6; negation valid 5/6 correct 3/6; taxonomy valid 1/6 correct 0/6. Invalid answers stay in the 24-task denominator. There are no independently held future tasks in either arm.

## Original records, independent arithmetic, resource boundaries
- `execution.log`, `execution/RESULT.json`, `execution/PREEXECUTION.json`, `execution/ROWS.jsonl`: original model-run stdout, 24 full outputs/tokens, 24 attempts and 24 completions, model/source/config/roster pins; unedited data.
- `INDEPENDENT_AUDIT.py` and `INDEPENDENT_AUDIT.json`: separate Python stdlib verification of 24 task identities, answer parsing, labels, 49 ordered journal events, per-row correctness, hashes of all six source files and eight model assets, and exact source Git commit/tree. Recomputed **12 valid, 6 correct, 0 first EOS**, with no silent null→success mapping. This audits recorded outcomes, **not** a separately sampled evaluator or independent new B.
- `/usr/bin/time -v` process log: **wall 8.92 seconds**, user CPU **30.36 seconds**, system CPU **0.37 seconds**, peak RSS **1,212,268 KiB**. The program-reported narrower interval is wall 8.35 sec, CPU 30.16 sec. The CPU/wall figures are different clocks, not alternate measurements of one resource.
- Existing model bytes were reused. Package installation, prior model acquisition, CI queue/setup, electricity, Owner lifecycle, cold recovery, network propagation and opportunity cost are **excluded** from the inference process-only figure. This is **not** a fully cost-matched 2×2 benefit result.
- `EVIDENCE_SHA256.txt` binds saved raw files. GitHub blob IDs and remote tree must be independently read back after publishing.

## Hold and permissions
**HOLD_NO_GO / DENY_ALL**. Reference/shadow CI status is separate from native true model output. No owner-attested source/action/feedback time alignment, Q24 production candidate, actual training gain, independent prospective B, legitimate Adopt/NoUpdate, distinct C NextUse, cold recovery, old-task or OOD retention, real MEM deletion, full resource-cost comparison, or Core×NDU 2×2 attribution was established. This is an exposed-format diagnostic only. No weights updated, PR merged, authority expanded, or model deployed.
