# E2 original DINO+Granite four-artifact independent audit (research / DENY_ALL)

## Purpose and separation

`e2_crossmodal_archive_audit.py` is **stdlib only**. It does not import the
model forward path, training fit, source author, scoring implementation or
network; it does not download checkpoints. It independently reads exact pinned
bytes from all four archives of the **same exact source SHA and run**:

1. `hepta-e2-crossmodal-source-no-future-targets` — includes approved source
   records and PNG bytes, and **no future target digests or files**.
2. `hepta-e2-crossmodal-withheld-evaluator-only` — independent future caption
   and class labels and the `target-manifest.json` bound by source manifest SHA.
3. `hepta-e2-crossmodal-sealed-producer-no-weights` — real original frozen DINO
   and Granite execution receipts, 16 TRAIN/8 FUTURE features, fitted/shuffled/
   unaligned bridge predictions and sealed class predictions.
4. `hepta-e2-synthetic-two-pretrained-stems-independent-outcomes` — Granite
   future-target embeddings and readout created by a separate physical job.

The command requires externally supplied SHA256 hashes of the **ZIP bytes**, not
merely the constituent JSON digests. It checks canonical JSON/JSONL, no
symlinks/absolute/parent paths/duplicate names, bounded expansion, exact member
inventories, all 24 PNG byte digests and source identity, train/future group and
time separation, immutable source-to-target plan, original DINO/Granite revision
and declared forward receipts, sealed prediction fingerprints, complete class
case labels, paired rescued/harmed counts, 384D finiteness, cosine/MSE and
within-panel retrieval, recomputed **without importing the proposer scorer**.

```bash
python3 experiments/shared_stem_cell/e2_crossmodal_archive_audit.py \
  --source source.zip --source-sha256 "<source zip sha256>" \
  --target withheld.zip --target-sha256 "<withheld zip sha256>" \
  --producer producer.zip --producer-sha256 "<producer zip sha256>" \
  --evaluator evaluator.zip --evaluator-sha256 "<readout zip sha256>"

python3 -m unittest discover -s experiments/shared_stem_cell \
  -p test_e2_crossmodal_archive_audit.py -v
python3 -O -m unittest discover -s experiments/shared_stem_cell \
  -p test_e2_crossmodal_archive_audit.py -v
```

## Historic run and nonclaims

The original prior-to-fix run [38677568171](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38677568171)
finished **four successful Jobs**, with actual published model execution and
independent synthetic eight-case readout: fitted 8/8; label-rotated control
0/8; unaligned 2/8. Frozen geometry mean cosine 0.943049216123495 versus
0.884433255385426 and 0.014649690886581. This is a true archived research
measurement on artificial geometric drawings **but** that run exposes future
label hashes in the model-producer-visible source-manifest. The strict new
auditor rejects it as `SOURCE_MANIFEST_TARGET_HASH_EXPOSED_OR_INVALID`.

A **test-only retroactive copy** of the four old ZIP contents with exclusively
modified manifest bytes passed the new offline scorer and recomputed 8/8, 0/8,
2/8 and all geometry scores. This is *not* a fresh physical run, accepted
historical data, or a repair of the old provenance. The actual corrected source
code resides in Draft #2174 and requires its own physical completed four
artifacts before independently passing this auditor.

Even if the re-run passes, `actual_model_receipts_consistent=true` is only an
archive/source-integrity statement; a ZIP plus hash is **not** independent
publisher or physical-host attestation. The classification labels are from
public deterministic synthetic generator code. Natural-image OOD generalization,
semantic human-reviewed labels, equal-cost original-421M comparison, OCR/native
EmbeddingGemma five-arm parity, 3 real future windows and genuine NDU/FinalUse
production utility are **not** established. All outputs are permanently
`production_accepted=false` and `authority=DENY_ALL`.
