# HPCA B2 exact arithmetic control — real task-identity-matched negative baseline

**Decision: HOLD_NO_GO / DENY_ALL.** This follow-up to PR #5950 runs a separate exact, deterministic arithmetic control on the original 60 operator-created B2 prompts. It is a direct computation control, not a newly trained model, a novelty claim, independent B custody, an Agentd owner operation, or a production candidate.

## Immutable input and comparator

- Parent evidence and original model outputs: [PR #5950](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5950); base commit `0f58988a48fc922f16c4a1b8cf2f4373e4c07c15`.
- Unmodified operator B2 task manifest: SHA-256 `0f12ac4aa7fd32989ba62983ed82367b83fe6a3f51868e4c1b8f567a9decf12a`.
- Unmodified 9-run, 540-row original CPU scoring archive: SHA-256 `937a87f1da2e502f954be0870cd3a64ce06df0245938fc984b8b2a5ed0d95731`.
- Actual originally trained SmolLM2-135M LoRA output remains as reported in #5950; these are **operator-built arithmetic tasks** and two-choice scored model outputs, not independently withheld future B.
- On `ai395`, the script was executed over **the original immutable bytes**, with separate exact-family parsing (not a key lookup, not labels) for evenness, inequality, divisibility, set membership and primality.

## New results (original ai395 execution)

| Exact operator task B2 control | Correct / decisions | Qualification |
| --- | --- | --- |
| Frozen base + 8 actually trained LoRA original two-choice runs | 270 / 540 = **50%** | All 9 runs predict 'no'; from retained actual inference archive |
| Exact arithmetic rule, same 60 prompts repeated for nine evaluations | 540 / 540 = **100%** | Rule derives answers directly from prompt syntax, not target labels |
| Per family exact arithmetic rule | 100% in all five families | In-domain only, not OOD/generalist intelligence |

- Independent new Python test suite: **4/4 pass**, including opposite-label examples for all five families, strict grammar rejection, archive-corruption rejection, and full original held dataset comparison.
- Python 3 local run, no packages, no model weights, no optimizer or new model inference.
- Warm arithmetic decision loop for 540 decisions: **0.000639158 s wall, 0.000637301 s process CPU**, process peak RSS **18,136 KiB** (includes interpreter and loaded manifests). These are **partial process-loop** costs and cannot be divided into the original nine scoring-process wall/CPU numbers to assert a full-system speedup.
- Original model scoring-process **sum** 24.313295296 s wall / 92.954481356 s CPU, reported by prior evidence; different measurement envelope and processes. No energy, I/O, acquisition, model initialization or true owner lifecycle matched.
- Raw replayable files: `B2_RULE_RESULT.json` (540 decision aggregate + one 60-task prediction roster), `B2_RULE_TEST.log`, `hpca_b2_symbolic_control.py`, and `test_hpca_b2_symbolic_control.py`. Input original files live unchanged in parent #5950.

## Consequence for research

This B2 slice should **not** be used to claim the benefit of a new neural plasticity clock, reward-credit routing or memory policy. Its obvious deterministic admissible computation baseline already perfectly handles the admitted syntax while the observed trained adapters make constant 'no' choices at 50%. Neural B2 must be treated as negative diagnostic evidence; comparative experiments need genuinely nontrivial future tasks where deterministic exact computation/RAG and low-cost baselines are explicitly matched. The exact control is brittle to wording changes and not an open-ended language solver.

No model adoption, credentials or permission changes; no new owner evidence; 2x2 Core×NDU, independent B/selector, different C, ACT/CTRL real effects, memory tombstones, old/OOD retention and cold restart remain **HOLD**.
