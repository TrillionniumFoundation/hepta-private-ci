# P0 V9 — Repair actual pretrained experiment dispatch without weakening four-model gates

**RESEARCH / DRAFT / DENY_ALL.** This is a narrow execution-correctness repair on the existing P0 V8 lineage. It does **not** select a model, train a new production Stem, change the task corpus, introduce authority, grant FinalUse, modify the original Neuron/CNS/Control/WAL/CAS owners, or assert any new real pretrained benchmark result.

## Proven source defect: V7 CLI cannot run

The original `independent-original-head-training` job passed two extra Python source file paths **between** `p0_independent_training_replay_v7.py` and `--fit`. The actual source CLI declares **only named** arguments. Once upstream stages complete, `argparse` exits with `unrecognized arguments`, before any independent 40-step SGD runs. V9 removes those two positional arguments and adds a test that executes the actual V7 parser both with the historical malformed argv (must reject) and repaired argv (passes parsing, then stops at deliberately missing fixture file). No train/scorer code is altered by this fix.

## Independent real-model preparation rather than cross-cancelling

Previously `physical-four-models` required *both* compact snapshots and the Gemma checkpoint and `laya==0.3.20` dependency to be installed **before** attempting Granite. If any unrelated model acquisition failed, Granite could not produce even a partial physical result. V8's downstream partial numerical reviewer could then only observe missing data.

V9 separates the **existing pinned source acquisition** for each model:

- `p0_pretrained_checkpoint_preflight_v9.py` checks the exact Granite R2 and mmBERT-small upstream 40-character Git revisions, the same safe allowlist (`*.json`, `*.safetensors`, `*.txt`, `*.model`), original mandatory model/config/tokenizer files, forbidden pickle/PyTorch/remote-code suffixes, and SHA-256 of declared LFS files. The original *model loaders* remain the only physical pretrained model execution path; in particular, mmBERT's complete tied-weight attestation remains unchanged.
- Missing/wrong/broken material creates an explicit model-specific, create-only `<model>.failed.txt`, with a **sanitized exception class** only. An independent model continues to preflight and execute; no fake pretrained weights, no retries that silently select another revision, and no permission grant.
- Gemma pinned text checkpoint preparation is separately timeout-bounded. Failure creates `embeddinggemma_2_text.failed.txt` without suppressing the Granite/mmBERT attempts. The model must still have its actual manifest.
- The pinned Laya Python dependency is installed only immediately before the **last** Laya attempt, after the three Encoder experiments. If unavailable, the original native Laya arm remains `unavailable`, rather than invalidating a successful earlier compact-model attempt.
- The original main job still requires **all four** real `<model>.json` results and exits nonzero otherwise. V5/V6/V7 and original human-label scoring still depend on that nonzero status; V8 partial-only diagnosis remains `DENY_ALL` and never participates in success/selection.
- Original public artifact staging uploads only the bounded original outputs, `.failed.txt`, the small source preflight receipt, and prior permitted replay objects; it still excludes the foundation checkpoint directories and human-held label files.

The preflight's short `compact-preflight-v9.json` is a local **self-report**, not a publisher signature, and always records `whole_four_model_success=false` and `production_promotion_permitted=false`. A success-shaped local source manifest cannot substitute for a physical model-load receipt, nor can it approve a Head or scientific conclusion.

## Actual test evidence and remaining blocks

The new tests use fake local model files with real byte-hash checks and adversarial failures. They prove the error-isolation and CLI contract *mechanics*, **not** a physical Granite/mmBERT/Gemma/Laya run. New tests cover wrong revision, missing tokenizer, altered LFS weight bytes, untrusted pickle fallback, symlink output, existing failure-slot overwrite, both/one-model failure, secret-safe reporting, and the historical V7 CLI parse failure. The unchanged original P0 experiments are run again in ordinary and optimized modes on the exact authored files; Git blob and workflow syntax receipts belong to this new candidate SHA, not inherited earlier green statuses.

**Explicit blockers:** The exact-hosted P0 Source/Material/Producer/V5/V6/V7 chain must actually run to completion; an individual model's original success must be backed by raw source-bound artifacts and independent re-forward. Verify original human MultiRC labels, same-target Evidence vs trained Question-only quality, end-to-end cost, adequate hard semantic evidence and statistically useful future/OOD source groups before Stem choice. Global `blocking-ci`, Architecture source-head/base-merge and independent CAS/Evidence WAL/FinalUse remain mandatory and separate. CPU/GPU p99/energy, multimodal generation, NDU/FBSDE superiority and Compiled Skill Cell claims are **not** established.

**Do not merge, select a model, or activate production from this research.**
