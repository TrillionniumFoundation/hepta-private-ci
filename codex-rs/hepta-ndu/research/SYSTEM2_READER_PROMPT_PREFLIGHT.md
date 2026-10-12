# Frozen Reader: actual 100-call multi-hop failure and prompt-only intervention

Research-only increment under [PR #1546](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1546). This experiment does not alter production, train a Cell, add an Encoder, replace the Reader, revise the native NDU/Riccati/FBSDE numerical backend or merge into main.

## Verified real-model evidence — not a predicted result

The previous *hosted* synthetic 20-question/5-arm trial [run 38230686420](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38230686420) **completed successfully**, all 100 of 100 Reader calls, zero execution failures and the full MemoryCell regression (1,216 passed, seven skipped, 1,223 total). Generating source commit `7784872ebb8936865b4245f423d3aa2bb9e0a39d`. Its artifact `11743040489`, archive SHA256:

`7a0cb798418e7b00ac5258c26617f05e547be9f4c428bb82fb13428ec98647e2`

The read-only audit verifies all **22** internal SHA256 manifest entries, `native/raw-answers.jsonl` seal SHA256:

`774bf1a79113f1b6e2d1ef084ebb4c147692c0ab70145e04a7c16ae5b1b0ce25`

and recomputes the complete 100-cell scorer, original selected-source identities, excerpt **byte equality** to the original question-specific source, query digest, frozen Reader/model profile and deterministic duplicate request identity. It rejects re-sealed tampering, duplicate or missing conditions, changed citations/source fields and answer drift. There are only 20 distinct questions and 91 distinct deterministic prompt requests; **100 calls are not 100 independent tasks**.

The actual completed frozen Reader results are **negative**:

| Evidence arm | Complete source sets | Strict task success | Proper bounded `[E#]` citations | Exact abstentions | Target token *literal* appears | 64-token output cap reached |
|---|---:|---:|---:|---:|---:|---:|
| no_evidence | 0/20 | 0/20 | 0/20 | 0/20 | 0/20 | 0/20 |
| bm25_top3 | 4/20 | 0/20 | 0/20 | 0/20 | 6/20 | 18/20 |
| lexical_top3 | 2/20 | 0/20 | 0/20 | 0/20 | 6/20 | 14/20 |
| joined_top3 | **20/20** | **0/20** | **0/20** | **0/20** | 7/20 | 11/20 |
| premise_removed | 0/20 | 0/20 | 0/20 | 0/20 | 11/20 | 19/20 |

The output frequently starts `E1: ...`, repeating evidence as prose rather than citing it in brackets; **`E1:` is NOT `[E1]`**. Target-token literal mentions are neither grounded answers nor independent judgments. The 64-token saturation suggests copying and verbosity, but does NOT prove this is the only reason the model fails. Five prompt-candidate changes chosen after seeing these results are *not* out-of-sample qualification.

## Next experiment — isolate prompt/representation vs model capacity

Keep the original exact model weight hash `afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c`, original decoder (`max_new_tokens=64`, greedy, same generation config), and the original `no_evidence`, `joined_top3`, `premise_removed` source sets for each of the **same exposed 20 fictional English tasks**. The original 60 answers are taken directly from the externally SHA-pinned archive; **they are not regenerated or silently edited**. Before issuing any new model call, recompile every original prompt using the current frozen tokenizer and verify its exact `input_ids_digest`, source bundle and model profile match the archived original.

Run exactly three new prompt-only variants on the **same one shared model object**:

1. **direct:** Keep the original JSON evidence representation; replace only system instruction with explicit one-line answer plus all supporting `[E#]` citations or exact insufficiency refusal. No intermediate reasoning text or evidence enumeration.
2. **demonstrated:** Same JSON and decoding as direct, plus two fixed in-context demonstrations of a supported and an unsupported relation. The demonstrations are unrelated to the held-out question IDs and contain no generated gold labels for the test tasks. This is additional prompt-context compute, not training.
3. **compact:** Same system instruction as direct, but render the complete identical evidence bytes in one labeled plain-text block instead of JSON. No evidence is truncated or re-ordered.

Scheduled new neural calls: **20 questions × 3 evidence conditions × 3 prompt variants = 180 calls**; 60 prior original outputs are immutable controls, for 240 registered comparisons. The three variants may have different *actual* input-token counts; **this is not an equal-token claim**. Output cap, model, all selected source identities, decoder and source-time conditions are identical. Full raw answer and model/format/input token receipts are flushed/fsynced and sealed before scoring. If an answer call fails, it is retained as a failed/unknown attempt and the run fails closed; it is never a fabricated wrong model prediction.

The fixed **primary** prompt variant is `direct`; it qualifies for *independent confirmation*, not deployment, only if **at least 15/20** full-evidence answers have exact target + complete bracketed source citations, **at least 18/20** no-evidence queries abstain exactly, and **at least 18/20** missing-premise queries abstain exactly. `demonstrated` and `compact` are diagnostic arms and cannot be chosen as a positive winner after seeing these exposed test scores. The old 60 controls and the full model identity must pass replay first. Independently adjudicated semantic citations and truly fresh natural tasks remain mandatory before any general benefit claim.

## What these tests do not establish

The synthetic grammar was created and seen during method development. Textually copying a target token, avoiding a fake instruction, or returning a correctly formatted `[E1]` does not prove general language reasoning or supported citations. A prompt candidate that fails this preflight should be stopped, not rescued with post-processing that invents citations. Prompt-only improvements, if any, are **not learned NDU/FBSDE** or MemoryCell value learning. Independent evidence sufficiency, refusal, citations on real records, calibrated uncertainty and matched real inference costs remain required.

All research code stays on the draft branch; there is no production switch. Existing multi-hop, quote-stress, counterfactual Reader, 384-answer archive and arithmetic search experiments remain unaffected.

## Reproduction

The workflow `.github/workflows/hepta-system2-reader-prompt-preflight.yml` pins the original actual-run ZIP, verifies all entries and source identity, runs the **full MemoryCell unit-test suite** with Ruff F/E9 checks, stages only the pre-existing Reader from pinned historical artifact `11586991191`, and runs the prompt trial offline with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`.

From a full checkout with the Reader staged and original artifact present:

```sh
export HEPTA_MEMORY_TESTED_COMMIT="$(git rev-parse HEAD)"
export HEPTA_SYSTEM2_COMPLETED_MULTIHOP_ARCHIVE=/tmp/completed-multihop100.zip
python scripts/memory_cell/system2_multihop_completed_audit.py \
  "$HEPTA_SYSTEM2_COMPLETED_MULTIHOP_ARCHIVE" /tmp/completed-multihop-audit.json
python scripts/memory_cell/system2_multihop_prompt_trial.py \
  /tmp/memory-inputs/reader "$HEPTA_SYSTEM2_COMPLETED_MULTIHOP_ARCHIVE" \
  /tmp/multihop-prompt-out --development
```

The raw-answer SHA seal, exact source commit/tree, model inventory, total CPU, every prompt's token costs, original and new outputs, negative controls and exception journals are preserved in the uploaded artifact.
