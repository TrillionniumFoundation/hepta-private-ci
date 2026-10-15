# E23 — original human mixed-answer obstruction certificate for current E21 Reader policies

**Research only: DRAFT / DENY_ALL / NO_MODEL_SELECTION / NO_PRODUCTION_SYSTEM2.**

E23 is a strictly additive child of original E22 [PR #2288](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2288), starting at exact source SHA `32bf7cad765335a052bd49094af05b0f7cab16b1`. It does not edit the original frozen/trained E15 Heads, original E14 data, original E21/E22 scoring implementation, `neuron.runtime`, `utility.ndu`, `learning.plasticity`, CAS/WAL, CNS, FinalUse, or main.

## Stronger original evidence without reading raw labels

This is a **physically executed local numerical replay of three successful, SHA-locked original GitHub Actions ZIPs**, using archived human-label **aggregate observations**, plus the E22 authentic frozen/held-fold original pretrained model predictions:

- [Real E14 original human score run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38679381761): artifact `11947358809`; complete ZIP SHA `efd3525b6c412b1681333b1f1185a6879973ae93340b12f786139eb45a3ff0f4`. Its separately evaluated human outcome says `all_questions_mixed_original_labels=true` on **8 questions / 4 original passage groups / 33 dependent candidates**.
- Real E15 independently produced source-HEAD original human-score ZIP `11950611472`, SHA `f332ab92181a0e088d941dbf4c77165ab2e4c40e48e9bbda4915e8d1543aceb8`; and separate synthetic-merge original human-score ZIP `11950935731`, SHA `63da90cb7da7f2f6ef478e44731e548a62a4b3c1a071593864f23b5896290acc`. Both declare **8 mixed-label original questions**, 4 heldfolds, exact source IDs, and independently numerically agree on the six original Reader candidate accuracies/Brier and passage counts. Four frozen arms additionally reproduce the E14 human scores.
- E22's genuine original prelabel predictions from pinned ModernBERT model ZIP `11946621518` and four original **trained** E15 held-fold ZIPs; exact rejoined E21 original-source blind JSON SHA `afa0fc674b4608dceed8c0665efba1bc91604adb1c43de9ac155894f8f200084`.

The new code opens **no raw human MultiRC validation parquet and no original-human per-candidate labels**. It verifies both the ZIP outer SHA and their internal score SHA before checking original model/source/held-label identifiers, zero production authority, cross-artifact human candidate-score agreement and mixed-question census. It computes a strict **conditional upper bound**, assuming the prior independently reviewed human-annotation summary is truthful, not a replacement for source-label re-derivation.

## What the bound actually proves

Because every original human-labeled question contains both a true and a false candidate, any **unchanged binary inference policy that emits one hard class for all candidates in that question** necessarily fails complete-question classification. Counting only observable no-label predicted hard classes thus yields:

| Original Reader | Questions with same hard class / 8 | Upper bound on complete questions with **unchanged** policy | Upper bound on complete passages / 4 | Exact constant-score questions / 8 |
| --- | ---: | ---: | ---: | ---: |
| conditioned | 8 | **0** | **0** | 4 |
| mean-pool + query | 8 | **0** | **0** | 0 |
| no-evidence | 7 | **at most 1** | **0** | 0 |
| no-query | 8 | **0** | **0** | 8 |
| learned 5-param linear | 8 | **0** | **0** | 0 |
| learned 3-param gated | 8 | **0** | **0** | 0 |

The original no-query arm's **19/33 candidate accuracy** must not be marketed as successful whole-question reasoning. Its score is *exactly constant* across all eight mixed-label questions: no deterministic post-processing of **only that score** can discriminate the positive/negative alternatives. For `conditioned`, that exact-score-only impossibility applies to four questions. For other arms, nonzero probability variation **may contain useful unexploited information**; their zero bound applies only to the **currently frozen threshold/Head policy**, NOT all future trainable Readers or any NDU architecture. A better Reader, extra evidence, a different learned calibration, or access to candidate text changes the premise.

This is a *certificate about the current policy on the eight original questions*, not 8 statistically independent future problems. Four passages are correlated; no confidence/power, OOD or source-family claim follows. The actual complete-question human result still requires original E21/E22 independent postseal scorer if exact correctness, not just bounds, is desired.

## Executed and retained artifacts

- `e23_mixed_question_certificate.py` reopens actual E14+E15 ZIPs and E22 source-locked prediction contract; each tampered/missing archive or forged mixed-label score is rejected.
- `test_e23_mixed_question_certificate.py`: 12 original-ZIP-backed tests completed locally under normal Python **and** 12 under `python -O`, no skips/failures. They test legacy original score and full source/fold parity, false human mixed-label observation, changed true model output, missing independent second score, exact-vs-hard invariance distinction, create-only output and no authority.
- Sanitized actual local output is retained in `E23_REAL_ARCHIVED_MIXED_QUESTION_UPPER_BOUNDS_20261015.json`. Full 8-question per-arm diagnostic produced locally has SHA-256 `5df63a38378848e0dc9829b0346de23f09c462ff36657fc9c8d3b5133c192c6a`; it is a **local tool observation**, not an external host signature.
- The E21/E22 original two-phase workflow is **extended, not replaced**. In the independent postseal stage it must download exact E14 human archive, keep the existing original validation parquet/E21/E22 scoring stages, run new E23 original-ZIP tests in both modes, compute the E23 certificate, and compare all six arm bounds with committed original observation. New exact-head CI must **finish**, not merely be queued.

Running locally, with authentic original artifact bytes:

```bash
export PYTHONPATH=qualification/shared-stem-system2-architecture
export HEPTA_E23_BLIND=/pinned/original-e21-sealed-blind.json
export HEPTA_E23_E14=/pinned/e14-original-human-score.zip
export HEPTA_E23_E15_SOURCE=/pinned/e15-source-score.zip
export HEPTA_E23_E15_MERGE=/pinned/e15-merge-score.zip
python -m unittest discover -s qualification/shared-stem-system2-architecture \
  -p 'test_e23_mixed_question_certificate.py' -v
python -O -m unittest discover -s qualification/shared-stem-system2-architecture \
  -p 'test_e23_mixed_question_certificate.py' -v
python qualification/shared-stem-system2-architecture/e23_mixed_question_certificate.py \
  --e21-blind "$HEPTA_E23_BLIND" \
  --e14-original-score-zip "$HEPTA_E23_E14" \
  --e15-source-score-zip "$HEPTA_E23_E15_SOURCE" \
  --e15-merge-score-zip "$HEPTA_E23_E15_MERGE" \
  --output /new/create-only/E23-certificate.json
```

The scripts are not a sandbox or an issuer authenticator. Even three consistent previous scorer ZIPs cannot independently prove original source content licensing, held-label privacy, full-model runtime p99, device/energy ownership or future transfer. Preserve exact predecessor E21/E22 negative findings and `reader_information_sufficiency_accepted=false`, `full_NDU_system2_admitted=false`, `production_accepted=false`, `authority_posture=DENY_ALL`. Do not merge to main or make a 10T/100T claim.
