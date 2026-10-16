# V18 — Original 135M Reader evidence/prompt serialization, 30 original human questions

**RESEARCH ONLY / DRAFT / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL / NO MAIN MERGE.**

## Scientific issue and precise ancestry

This incremental child of [V17 original source-first 135M Reader #2492](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2492) holds fixed the V17 ten original LoCoMo conversation roots (`conv-26/30/41/42/43/44/47/48/49/50`), three SHA-lowest question IDs per root, source-only public utterance/question material, publisher witness **source addresses only** (not targets), exact model tensors and tokenizer.

V17 genuinely executed 96 physically unique Reader prompts from 120 logical question/arm requests and independently reviewed the original answer, token and model-call journal. Its initial publisher answer-strict-equality proxy was 0/30 in all arms. Publisher answers are **missing in 8/30 V18 fixed questions** (not demonstrably wrong predictions). V18's new review explicitly censors those cases from answer-literal denominators.

This V18 does *not* execute a larger reference Reader; an independently signed human reviewer; prospectively disjoint future questions; a trained Cell Head; an NDU FBSDE; an actual System 2 planner; or a multimodal generator. It is a falsifiable **same-model, source-address-fixed, changed-prompt diagnostic**, not a proof of a general optimization gain.

## Real executed conditions

The old original V17 `none` and `annotated` 135M outputs are frozen comparison arms, not free new model calls. Every new variation uses the same original BPE, immutable model, 24-token greedy output cap, exact question and (where applicable) the exact 240-character maximum of each publisher-selected original utterance with the same evidence markers. Source answer fields are never read by plan/model processes.

- `plain_none`: plain QA wrapper with zero evidence, 30 new actual model inputs.
- `plain_annotated`: same plain QA wrapper with the original annotated utterances, 30 new actual model inputs.
- `role_annotated`: alternative chat-role/short-answer wrapper over those identical annotated utterances, 30 new actual model inputs.

The proposer precommits and SHA-binds every raw input plus owner/parent/annotation revisions. **No data-dependent training or prompt optimization is performed.** Source and instructions differ between the two annotation-bearing formats; model input lengths, token counts and compute are charged separately. Therefore there is no *equal-token* or *equal-cost* result from merely comparing raw scores.

## Physically executed original observations, 2026-10-16

Original source/model weights: GitHub Action archive **11586991191**, archive ZIP SHA256 `07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`, 30-layer 135M BF16 original model weights SHA256 `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`, original tokenizer SHA256 `9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c`, publisher LoCoMo SHA256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`. Original raw bytes remain local, outside Git.

**90/90 genuinely unique new exact model inputs physically executed, 1,773 real model forwards, 232.297 CPU seconds and 120.527 wall seconds.** New inputs comprised 8,462 physical input tokens and 1,706 generated tokens. Each physical request was recorded in a create-only 0600 fsynced start journal before inference. An independent source and token auditor revalidated the original V17 96-prompt physical result, then all 90 new token-ID/answer/forward/cost/source bindings. It ran postseal publisher-label comparisons and disclosed missing labels. Numerical runtime is a manual Torch FP32 CPU implementation on original BF16 weights, **not official Hugging Face operator/tokenizer parity** or an independent signed host.

| Fixed condition | Original question population | Publisher answers actually present | Weak literal target substring | Strict full publisher answer equality | Input/output tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| V17 `none` | 30 | 22 | 0/22 | 0/22 | 2058 / 339 |
| V17 `annotated` | 30 | 22 | **5/22** | 0/22 | 3784 / 635 |
| V18 `plain_none` | 30 | 22 | 0/22 | 0/22 | 1548 / 467 |
| V18 `plain_annotated` | 30 | 22 | 2/22 | 0/22 | 3277 / 559 |
| V18 `role_annotated` | 30 | 22 | 3/22 | 0/22 | 3637 / 680 |

Each arm is a repeated sample from the *same 10 historical original conversation roots*, not 30 independent data families. Strict match is a weak exact-string test; substring is even weaker. **Neither is independently adjudicated semantic accuracy.** The `annotated` source is a publisher annotation, not a human-certified sufficient witness. Many outputs contain dangling or unsupported `[En]` markers; counting them does not certify citation entailment.

Measured output changes versus original `annotated`: `plain_none` 30/30, `plain_annotated` 30/30, `role_annotated` 27/30. Changed output bytes are not evidence of success. The exact reader/Head/pretrained system is not optimized or updated by this test. No NDU or System 2 improvement is inferred.

## Independent adversarial review

The V18 reviewer reconstructs exact source IDs, formatted sentences, question, prompt SHA, original tokenizer IDs and all generated output IDs without importing the V18 proposer, then cross-checks the separate V17 original source auditor and the original physical journals. Real private sealed materials underwent **nine** mutation experiments, **all rejected**: answer text replaced despite re-signed hashes; forged model forward count; false production claim; re-signed evidence ID substitution; shortened and re-signed start journal; modified publisher truth; negative measured CPU costs despite re-signed response digest; modified model-source digest; fabricated semantic-success field. This is independently authored software and a distinct process, **not an independent organizational signer or immutable external evidence owner**. Source-only synthetic tests separately check additional invariants.

**22/22** local source-only `unittest` passed using Python `-S`; **22/22** repeated under `python -O -S`. Tests include fully re-signed source edits and intentionally wrong authority claims. The model and publisher corpus never appear in tests or commits. The hosted Actions workflow reruns both modes on the actual child HEAD, independently reloads original pinned tensors/source, genuinely reexecutes V17 and V18 physical model forwards and nine private adversarial checks. Until hosted jobs finish, the local result must not be represented as a hosted exact-HEAD success or an externally verified task-quality win.

## Repeat / scope

Read-only source tests on the stacked PR branch:

```sh
export PYTHONPATH=research/hepta_v17_reader:research/hepta_v18_reader
python -S -m unittest discover -s research/hepta_v18_reader -p 'test_v18_prompt_trial.py' -v
python -O -S -m unittest discover -s research/hepta_v18_reader -p 'test_v18_prompt_trial.py' -v
```

Physical reexecution is specified in `.github/workflows/hepta-v18-original-reader-prompt.yml`, which requires the immutable original GitHub artifact and original model SHA. Only sanitized independent score and mutation receipts are uploaded. No raw prompts, source utterances, source+target pairs, original tensors, model outputs, original publisher labels, user data, or credentials are committed.

## Next qualified priority

Run **physically pinned stronger Qwen3-0.6B** against the **same 30 source-first questions and the same evidence IDs**, with a separate frozen chat template and model SHA; include 0/2/3+ evidence conditions, actual full lifecycle compute, original independent semantic/citation adjudication and source-family clustering. A stronger Reader's gain is **Reader capacity**, not Cell Split or NDU. Only if the fixed Reader has sufficient-evidence competence and real task success does one evaluate adaptive System2 selection/STOP against ordinary same-utility dynamic programming. This V18 has **no** such proof; keep `HOLD_NO_GO`, `DENY_ALL`, and `no main merge`.
