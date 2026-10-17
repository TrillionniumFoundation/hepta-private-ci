# MemoryCell — 48 physical Reader format probes (October 16, 2026)

**Status: completed CPU research; DENY_ALL for parameter-memory promotion and production.** This is an exploratory follow-up on the same eight previously exposed LoCoMo conversation roots. No independent future source population or human evidence-sufficiency verdict is claimed.

## Exact generating provenance

Original physically executed Python: scripts/memory_cell/locomo_format_trial.py, Git blob 78859c6f617c28297f5f03f13fa7c443de49bedc, SHA-256 3cf5329c6d5fc500a4252e5cdbdae1f3e281dfac0cb48bc1c15b85a27bfc6ed3. Preserve this file unmodified rather than post-hoc formatting it.

Earlier sealed question/evidence input SHA-256: fa7d9e676f9aca8f7c524e6f592cabb88a22c490a8c441db4bd6a8e05fbc6033. Pre-inference registration SHA-256: 66fcf3f8da9c7992c5b83a1f0b5b4bbf9c90733c5e3444522ff44a40ffd6b655. Sealed 48-request plan SHA-256: 201914d85ea2d2b7c2db37b460dff535bae57f42aa8f0c3dd72152f33c482bea. These plan files were written before the new model calls; the publisher answer fields were not read during preparation or generation.

Pinned original Smol135 FP32 model ZIP (GitHub artifact 11586991191): SHA-256 07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af. Executed with custom original Torch 2.10.0 CPU kernel, with original model/tokenizer file checksums. Official Hugging Face operator parity and Torch 2.5.1 parity are NOT established.

Conditions: 8 original public questions x [no evidence, original publisher-annotated witness plus unchanged distractors] x [prior original JSON, flat labeled evidence, question-first presentation] = **48 real neural model requests**, all successful. Same model weights, source eligibility and 1200/24 maximum input/output tokens; actual consumed tokens vary across formats. No training, new source family or changed task definition.

Current raw journal SHA-256: 1d8fc82f4843b8805709e1d60d878f0e9154099dcb0e33a773fae972e1a0b710. A second model-free process rechecked source and answer bindings, and all **16 exact repeated original JSON prompt responses reproduced identical generated-token SHA-256** from the previous 32-call raw journal SHA-256 1e36a1dcfefabf8d8912b81e215a9e7383bc4eb08a63e2dc592a0b46ce65aab3. This does not authenticate the original hardware or create independent tasks.

## Results on the eight already published questions

| Evidence | Presentation | Strict correct | JSON echo | Structural citation slot | Mean token-F1 |
|---|---|---:|---:|---:|---:|
| Annotated | Original JSON | 0/8 | 7/8 | 0/8 | 0.012500 |
| Annotated | Linear evidence | 0/8 | 0/8 | 5/8 | 0.061080 |
| Annotated | Question first | 0/8 | 0/8 | 1/8 | 0.135897 |
| Empty | Original JSON | 0/8 | 3/8 | 0/8 | 0.020833 |
| Empty | Linear evidence | 0/8 | 0/8 | 0/8 | 0.031136 |
| Empty | Question first | 0/8 | 0/8 | 0/8 | 0.021364 |

Changing format reduced prompt echo but did **not** improve strict task success. Structural citation slots are not semantic entailment; token-F1 is not task success. Models are not proven to have equal FLOPs or matched end-to-end cost. No result may be promoted as a MemoryCell gain.

## Post-seal evidence adequacy warning

The separate zero-inference audit opened original publisher answers only after both model journals had been closed. The normalized *entire literal answer* appears in the originally delivered annotated single-witness text for only **2/8** questions; in the full original conversation for **2/8**; in BM25 Top-3 **1/8**; and in the witness lesion **0/8**. Lack of literal match does NOT prove insufficient evidence (a paraphrase or inference could be needed). Conversely a match does not prove a witness is independently sufficient or causal.

Thus the 0/8 finding must not be labeled a strong proof of fundamental Reader incapacity. The two answer-literal cases also had zero strict successes, too few to generalize. The next proper comparison requires independently adjudicated sufficient contexts, a stronger frozen reference Reader, and genuinely new project families.

## Executable source and gates

Original executable: scripts/memory_cell/locomo_format_trial.py. Separate postseal reviewer: scripts/memory_cell/locomo_literal_sufficiency_audit.py. Read-only fixed-receipt verifier: scripts/memory_cell/locomo_format_result_gate.py.

From a complete pinned offline workspace:

    PYTHONPATH=scripts/memory_cell python scripts/memory_cell/locomo_format_trial.py prepare PRIOR_32_RUN NEW_48_RUN
    PYTHONPATH=scripts/memory_cell python scripts/memory_cell/locomo_format_trial.py execute NEW_48_RUN PINNED_MODEL_DIR
    PYTHONPATH=scripts/memory_cell python scripts/memory_cell/locomo_format_trial.py audit NEW_48_RUN PRIOR_32_RUN
    PYTHONPATH=scripts/memory_cell python scripts/memory_cell/locomo_format_trial.py score ORIGINAL_LOCOMO_JSON NEW_48_RUN PRIOR_32_RUN RESULT.json
    PYTHONPATH=scripts/memory_cell python scripts/memory_cell/locomo_literal_sufficiency_audit.py ORIGINAL_LOCOMO_JSON PRIOR_32_RUN NEW_48_RUN LITERAL.json

Source-only checks that do not download a model:

    PYTHONPATH=scripts/memory_cell python -m unittest discover -s scripts/memory_cell -p test_locomo_format_result_gate.py -v
    PYTHONPATH=scripts/memory_cell python -m unittest discover -s scripts/memory_cell -p test_locomo_literal_sufficiency_audit.py -v
    PYTHONPATH=scripts/memory_cell python scripts/memory_cell/locomo_format_result_gate.py

Ten format/census/adversarial tests plus three literal-source tests passed locally. A read-only GitHub Action will check the identical committed source and fixed sanitized outputs separately; queued/old-head checks do not establish an exact-head green result. The raw journal, source utterances, private prompts, and model tensors remain outside public Git; retained SHA-256 permits later source-origin reconciliation but does not substitute for independent model-host attestation.

No semantic citation precision, safe refusal calibration, actual original-project program repair, parameter training, prospective future windows, full extraction/index/storage/training/query/revocation/recovery TCO, final activation, production selection or deployment is established. Required blocking-ci/Architecture/HNMF/DecisionCell owners remain unchanged. **DENY_ALL**.
