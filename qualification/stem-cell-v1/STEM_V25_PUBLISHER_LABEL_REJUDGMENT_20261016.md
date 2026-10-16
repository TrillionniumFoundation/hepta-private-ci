# V25 — independently re-open historical public ScienceQA labels against the frozen V24 vision route

2026-10-16 · `TrillionniumFoundation/hepta-private-ci` · **DRAFT / RESEARCH_ONLY / SHADOW_ONLY / DENY_ALL**. An isolated successor of V24 PR #2537. No pretrained model promotion, live routing, model weights, global security/CI downgrade, `main` merge, NDU, physical Cell split, CAS/CNS, FinalUse or production side effects.

## The exact epistemic blocker addressed

The immutable original E3 Actions archive **11945106672** (run **38672941350**) has 64 raw sealed four-class probability predictions for each of eight model arms, 64 original case IDs and the original publisher-label file SHA, but intentionally excludes individual test labels. The original scorer reported 17/64 text-only, 21/64 image-only, 24/64 train-gate and 16/64 equal-fusion; its label and source files cannot be independently checked from that ZIP alone. V24 therefore honestly bounded its preregistered text-margin `<0.005` conditional image route to **5/64–33/64** correct. That wide interval is NOT observed task performance.

V25 builds a *different* read-only reviewer and source-ingestion gate: regenerate the original **same historical publisher source** from `lmms-lab/ScienceQA-IMG@b9984af01798586705cee1fbdfa80a6dcbef04f1`, using exact original `e3_scienceqa_stage.py` at Git commit `b8b2f10fe38506972301e77e3836729a90200673`. Check original stage/contract Git blobs SHA-1 `3ca8f55...` / `bd6d95...` before executing, check original dataset full Git revision and all Parquet LFS material through the original stager, then **require regenerated source and TEST-label file SHA256 equal the pre-existing original E3 ZIP seals**:

- outer E3 ZIP SHA256 `7807b82d6c747b0b13666b330145e3801a8c8a0aadeee3f2ff7ab5f5c8c00a30`;
- sealed prediction SHA256 `c91824b378357c60f6272b785233854eaa762efd8fadc421bf99b996a58dd8e4`;
- source JSONL SHA256 `a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202` (192 original train/cal/test cases, 96/32/64);
- held TEST labels SHA256 `b15cb81cbce3ff500ec58bb7da59c92801170bbce3b7995d689342505161f6d3` (64 original cases).

Only if **both** complete source and test-label byte hashes match, the independent new reviewer joins 64 original predictions to source and label IDs, checks complete group/material/source-prompt hashes, then recomputes accuracy, Brier, NLL and rescues/harms for **every** original arm without importing either the original trained model or original scorer. A changed target, source, case ID, probability, pairwise claim, bitstring or missing material fails closed. Historical conditional route then acquires a true ***retrospective*** accuracy from the 64 genuine original targets, not from inference of aggregates. It never estimates a physical 21-call speedup: the originally archived visual features were fully computed for all cases, so 21 remains a *planned* conditional call count.

The result is still **not independent human visual-necessity adjudication**: the public dataset's answer key is the same publisher data family and was historically exposed. Original stager and verifier are code in the same repository; a byte hash is not externally enrolled scientific custody or hardware attestation. No image lesion/change of source-media bytes was executed in V25. No new image/audio/video forwards, Head updates or independent future windows are performed.

## Actually executed locally on the available original archive

- Original outer 29,629-byte ZIP and 11 inner members verified; original 64 historical predictions and eight-arm source identity checked by existing V24 audit.
- New `v25_original_publisher_rejudge.py` recomputes all eight original arm scores **only when genuine independently re-downloaded publisher label bytes are supplied and match the archived TEST label SHA**. Without those bytes, the create-only public receipt is `STEM_V25_ORIGINAL_LABELS_HOLD_20261016.json` with `HOLD_ORIGINAL_PUBLIC_SOURCE_AND_LABEL_BYTES_NOT_REOPENED`, no task score and `DENY_ALL`. It cannot silently substitute guessed labels, numerical aggregates or synthetic data.
- `test_v25_original_publisher_rejudge.py` has separate synthetic/adversarial source contracts, genuinely archived model prediction/negative tests, and an **additional original publisher test class that fails (never skips) when the genuine source/label/stage material is missing**. Test counts and CI status must be updated only from actual command outputs; source-only green must NEVER be called a publisher rejudgment.
- Local container cannot reach Hugging Face's original 663 MB dataset by direct network; thus actual independent TEST label re-open and numerical route improvement are **not locally qualified**. The exact-head push-only read-only GitHub Actions workflow attempts the full original public source acquisition and independent score, uploading ONLY sanitized aggregate results. Queued/failing/skipped GitHub CI is **not** a completed V25 positive result.

## Running and interpreting the gate

```sh
cd qualification/stem-cell-v1
python -m unittest -q test_v25_original_publisher_rejudge.SyntheticContracts
python -O -m unittest -q test_v25_original_publisher_rejudge.SyntheticContracts
# The original archive must first be acquired and validated against SHA256.
export HEPTA_V25_ORIGINAL_ZIP=/private/original-e3-11945106672.zip
python -m unittest -q test_v25_original_publisher_rejudge.OriginalArchive
python -O -m unittest -q test_v25_original_publisher_rejudge.OriginalArchive
python v25_original_publisher_rejudge.py --archive "$HEPTA_V25_ORIGINAL_ZIP" --output /private/v25-historical-HOLD.json
# Only if verified original publisher stage exists:
export HEPTA_V25_ORIGINAL_SOURCES=/private/original-source/inputs/sources.jsonl
export HEPTA_V25_ORIGINAL_LABELS=/private/original-source/private_labels/test_labels.jsonl
export HEPTA_V25_ORIGINAL_STAGE_SEALS=/private/original-source/source-seals.json
python -m unittest -q test_v25_original_publisher_rejudge.OriginalPublisherPhysical
python -O -m unittest -q test_v25_original_publisher_rejudge.OriginalPublisherPhysical
python v25_original_publisher_rejudge.py \
  --archive "$HEPTA_V25_ORIGINAL_ZIP" \
  --sources "$HEPTA_V25_ORIGINAL_SOURCES" \
  --labels "$HEPTA_V25_ORIGINAL_LABELS" \
  --stage-seals "$HEPTA_V25_ORIGINAL_STAGE_SEALS" \
  --output /private/v25-historical-recount.json
```

## Next genuinely new causal/production prerequisites

1. Cross-modal **necessity** requires expert adjudicated independent examples, physically altered image content and controlled source-level lesions, not a replacement of an archived per-case probability column.
2. A real lazy visual Encoder must be executed on-demand on the same source/manifests/permission scopes; meter text/vision physical invocation, cache identities, private Cell inference, verification, CPU/energy/RSS and p95/p99, including all failed and abstaining requests. A replay from a fully encoded original batch is *not* a serving cost comparison.
3. Any Stem or expert decision needs an untouched post-freeze independently published source family/time window, genuine negative-transfer/retention and matched full lifecycle costs. Historic test-score improvements are not a model-selection result.
4. Independent source, model execution, evaluator, host and final-use custody must be established. Remain **DRAFT / SHADOW_ONLY / DENY_ALL** and retain all V20–V24 security/science gates.
