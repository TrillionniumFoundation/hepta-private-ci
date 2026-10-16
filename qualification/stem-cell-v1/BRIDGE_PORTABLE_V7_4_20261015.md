# V7.4 — Portable original Granite97 Bridge continuation, original source binding

**2026-10-15 · RESEARCH / SHADOW_ONLY / DENY_ALL · original V6 read-only · no main merge / production activation.** This is an additive successor to [V7.3 PR #2383](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2383). It addresses a concrete dependency: the historical V6 `design.json` contains absolute workspace paths such as `/workspace/scratch/.../reader-v5-binding/seed-41`, and the three user-held evidence ZIPs exclude the original 97M Granite model and TokenBank FP32 feature tensors. Restoring ZIPs to a different host does **not** make `bridge_gradient_campaign.checked_design` valid. Do not falsify that history by rewriting the old design.

## New source, actual functionality

`bridge_portable_v74.py` stages a **new** research experiment from the immutable V4/V5/V6 ZIPs. It reads their original train-only source rows, validates their byte and design ancestry, refuses arbitrary ZIP paths, duplicate JSON properties, altered or symlinked model files, wrong literal source identities or unqualified warmups, and preserves every original design/model/report byte. It does not copy pretrained weights or source text into Git.

Preflight authenticates three actual original-user-provided ZIP SHA256s:

| Input | SHA256 | Member count |
| --- | --- | ---: |
| `hepta_token_evidence_ndu_v4_20261015.zip` | `4fcfaa5a266fa3779b4c8af361570d959ea9f5880efb99fe99787bff81b6922c` | 313 |
| `hepta_binding_learning_v5_20261015.zip` | `0f3ef2cd1f80d4c8bf65b6da70c56ea8513d5a933db8c02e7db21a91ff168191` | 61 |
| `hepta_bridge_learning_v6_20261015.zip` | `197a5c68eb892970e6a7c7da4030fd2f468a3bf78a5cedfaf4c2667d3e54c58a` | 212 |

In addition to the whole-ZIP SHA, all 211 original V6 manifest member sizes and SHA256s are checked from a **single held file-descriptor snapshot**, not reopened after verification. The selected original V4, V5 and V6 design hashes and both original old/new source ID sequences are recomputed. The 3 genuine trained V6 Bridge warmup checkpoint SHA256 identities and original 500-step/seed sample plans are bound to the results; original 128 binding TRAIN rows, 3909 natural TRAIN rows and 827 natural previously exposed internal-tune rows are read in fixed order. Repeating seeds is not new independent data.

The `audit` phase does not execute Torch, download a model, invent missing tensor embeddings or claim to have completed a training run. Its sanitized receipt is committed as `V74_ORIGINAL_ARCHIVE_PREFLIGHT_20261015.json`.

When and **only when** an approved physical original Granite97 checkpoint is provided locally, `train`:

1. Verifies every model material file byte against **the original V4 encoder receipt**, including original revision `835ad14087e140460703cf0fae09f97d469d65c2`, original BF16 safetensors (194,889,568 bytes) and complete tokenizer, config, special token files. Requires the original V6 source runtime inventory to match unchanged source files.
2. Loads the original frozen Granite model via the repository's real `TokenBank` API. An optional `--cache` is accepted **only with byte-for-byte original V5 cache SHA**; a missing or differing explicitly requested cache rejects training. Without `--cache`, registers original source rows and **pays for new physical model encoding**. It cannot claim byte-identical historical feature reuse.
3. Loads all 3 *actual* trained V6 warmup `.pt` tensors (strict `weights_only=True`) and checks both the historical frozen Torch parameter digests and the independent Torch-free decoder. On the **actual original reencoded features** computes every 128-row old binding TRAIN probability with both a Torch Reader and an independently authored NumPy BridgeReader. NumPy/Torch outputs must agree within `0.0015`, and the original archived frozen model output must agree within `0.001` with zero class flips in each seed. If preprocessing/source material differs, training **fails closed before any update**.
4. Runs all 9 candidate arms, 3 seeds (41,47,53) × `joint`, `protect_old`, `protect_old_guarded`, each under the **unchanged original 500-step old/new row plan**, using the existing two-backward and post-Adam loss guard. Save candidate checkpoints and receipts once, together with original old-binding TRAIN outcomes, old-task protection and clearly descriptive previously exposed natural internal-tune diagnostics. New Encoder forward batches and actual training attempted/accepted/rejected steps are separately counted.
5. Never chooses a Cell, enables native NDU, uses official validation/future source labels, or infers generalization from a TRAIN-only result. No new empirical advantage is claimed before the **complete authentic 9-arm** execution and separate validation of source-disjoint outcomes.

`bridge_portable_v74_review.py` is a **separate standard-library reviewer**. It recomputes exact original source ID and paired-world correctness from sealed predictions, checks 9 actual saved model byte digests via restricted Torch-ZIP CPU FP32 decoding, rechecks original 500-step gradient identities and work counters, and refuses an incomplete 13,500 reported Reader forward / 9,000 reported backward census. It keeps all effects and promotion permissions denied. Even a fully passing future reviewer remains a **receipt consistency check**, not independent host/source attestation, a model training re-execution, an unseen-task result, or a general FBSDE solver.

## Actually completed in this authoring container

- Verified the three **actual** historical user Library ZIPs at the exact SHA above. Original V4→V5→V6 SHA ancestry, all 211 V6 manifest members, 3 frozen V6 head checkpoint byte identities and all original row/plan IDs passed.
- **28 / 28 local Python unit tests PASS, and 28 / 28 with Python `-O` PASS**, no skips. These use the three actual original archives and the three original V6 warmup **saved probabilities**; independent exact old train correctness is 128/128 and paired correctness 64/64 for each seed. The tests also reject label changes, source duplication, forged model bytes, wrong cache SHA, archive byte tampering, duplicate JSON properties and unauthorized result claims.
- Actual `audit` execution emitted `V74_ORIGINAL_ARCHIVE_PREFLIGHT_20261015.json`, SHA256 `c9c025447c62495892135d2085dd23875fd50c7e31f2865a013d63a2e932b69c`, with **`status=BLOCKED_MODEL_MATERIAL`**. Its `missing` list includes config, original safetensors, special-token map, tokenizer, tokenizer config, and `material.json`. This is **a truthful blocked preflight, not nine-arm completion**.
- The optional real pretrained `train` and full future-candidate independent reviewer execution **cannot run in this isolated host** because the original 97M checkpoint and TokenBank tensors are unavailable and network DNS access was blocked. Real `train`/future `review` behavior is implemented but is **not claimed validated end to end** in this environment. These are research-only fail-closed entry points.

## Reproduce with authentic materials

From a fixed repository checkout containing the additive V7.4 branch and Python 3.12, NumPy, PyTorch, `transformers==4.57.1`, the pinned tokenizer/Hugging Face libraries:

```bash
cd qualification/stem-cell-v1
export ORIGINAL=/sealed/original-evidence
export STEM=/sealed/granite97
# All three evidence ZIPs must already be available under ORIGINAL.
python bridge_portable_v74.py audit \
  --v4 "$ORIGINAL/hepta_token_evidence_ndu_v4_20261015.zip" \
  --v5 "$ORIGINAL/hepta_binding_learning_v5_20261015.zip" \
  --v6 "$ORIGINAL/hepta_bridge_learning_v6_20261015.zip" \
  --snapshot "$STEM" \
  --output /sealed/v74-real-preflight.json
```

Acquire the original **public** Granite model checkpoint under the immutable revision using the repository's existing approved source loader, **outside Git**:

```bash
python -c 'from group_encoder import acquire; acquire("/sealed/granite97")'
```

The original loader must verify all 5 material files, original upstream commit and tensors. An eligible `READY_TO_EXECUTE` preflight does not confer authority. Execute once from a *new* output path:

```bash
python bridge_portable_v74.py train \
  --v4 "$ORIGINAL/hepta_token_evidence_ndu_v4_20261015.zip" \
  --v5 "$ORIGINAL/hepta_binding_learning_v5_20261015.zip" \
  --v6 "$ORIGINAL/hepta_bridge_learning_v6_20261015.zip" \
  --snapshot "$STEM" \
  --output /sealed/portable-v74-candidates
python -S bridge_portable_v74_review.py \
  --v4 "$ORIGINAL/hepta_token_evidence_ndu_v4_20261015.zip" \
  --v5 "$ORIGINAL/hepta_binding_learning_v5_20261015.zip" \
  --v6 "$ORIGINAL/hepta_bridge_learning_v6_20261015.zip" \
  --run /sealed/portable-v74-candidates \
  --report /sealed/portable-v74-independent-review.json
```

Using the actual old prepared TokenBank additionally requires `--cache /sealed/original-v5-feature-cache`, and both `metadata.json` and `tokens.pt` must match the original V5 recorded file SHA; otherwise a supplied cache cannot be silently downgraded to a fresh experiment.

## Scientific gate remaining

No prospective independent source windows, no newly measured task-quality gain, no 4096-Cell target-host p99/RSS, no model-vs-Cell-split equal-lifecycle tradeoff, and no 10T/100T teacher equivalence has been established. Preserve frozen original V6 and protected `main`, and keep **all** NDU selection, trained CellSplit, model promotion and execution authority at **DENY_ALL**.
