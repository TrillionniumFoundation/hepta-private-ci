# V2 original-image source exclusions (640-source receipt)

This module closes one **data-preparation** blocker for the successor to the
frozen negative NDU grounding experiment; it does not close a multimodal
capability, long-horizon, covariance, compute-matching, or independent-test gate.

## Why an additional step is needed

The frozen v1 cohort builder accepts a single
`--exclude-manifest` whose schema contains
`source_sample.images`. Its original wrapper excludes the *earlier* 384
COCO images only. A truly new candidate must additionally exclude **all 256**
original images in the v1 train, dev, calibration and final-test splits.

`v2_exclusions.py` assembles those two pinned rosters into an exact,
deduplicated 640-source wrapper accepted **without changing the v1 builder**.
It pins both original input file SHA256 values, rejects modified or incomplete
rosters, validates source ID/COCO ID consistency and original-byte, RGB and
dHash near-duplicate collisions, and refuses nonidentical output overwrite.
It reads no reference boxes, outcomes, model predictions or generated pixels.

## Executed evidence

The original 831-file portable evidence archive was unpacked and the
assembler was executed against its actual historical wrapper and full
four-split v1 cohort manifest:

| Source | Count | Input SHA256 |
| --- | ---: | --- |
| Historical exclusion wrapper | 384 | `4c2b88f85c9ef5fea08790775a652798a72e9281bed1534561f14c681e7bba9d` |
| Frozen v1 cohort manifest | 256 | `71168c26fffdd913d71a69d8708cec957f55dc2bece112c9c50153fbf31de75d` |

The resulting **640 original images** have 640 different IDs and no detected
cross-roster duplicate fingerprint under the stated identity rule. Registry
SHA256: **`55c25e153f582633030004420f1babdf14188eef32814c006c16371eb78d298b`**.
The original v1 builder's actual `_exclusions` function successfully parsed
the generated file, read 640 rows, and returned exactly that checksum.
Fourteen local standard-library positive/negative controls passed, plus one Pillow-backed synthetic end-to-end integration of the unchanged cohort builder. That fixture built and validated four new sources while rejecting a historical ID without opening its absent JPEG.

The resulting JSON can be preserved as a separate artifact. The GitHub
receipt intentionally stores only the digest/validation instructions rather
than including the full historical fingerprints twice.

## Reproduce

Unpack the immutable original `hepta-ndu-evidence-v1-20261022.zip` and
set `V1` to the extracted directory:

```bash
python -m unittest discover -s qa/ndu-grounded-generation \
  -p 'test_v2_exclusions.py' -v
python -m unittest discover -s qa/ndu-grounded-generation \
  -p 'test_v2_cohort_integration.py' -v

python qa/ndu-grounded-generation/v2_exclusions.py \
  --historical "$V1/code/historical_exclusions.json" \
  --v1-manifest "$V1/cohort/manifest.json" \
  --output /path/to/v2-exclusions-640.json

sha256sum /path/to/v2-exclusions-640.json
# 55c25e153f582633030004420f1babdf14188eef32814c006c16371eb78d298b
```

For a **separate, explicitly source-isolated candidate** of the *same v1
grounding task*, the existing `cohort.build_cohort(...)` Python API accepts
`exclusion_manifest="/path/to/v2-exclusions-640.json"` and a distinct
`seed="predeclared-new-study-seed"`. Run the separate
`cohort_firewall.py` against both *original* history manifests after
constructing it. This recipe is **not** a validated protocol for long-horizon
or independently generated language/pixels; those need a newly frozen task
specification and actual model execution.

**Still open:** creation and freezing of a *new* v2 cohort, source versus
entity/pretraining contamination limits, 8–16 actual decisions, Cell
counterfactuals, covariance benefit under a nonzero risk policy, two
independent generated modalities, matched realized cost/coverage, multi-seed
confirmatory evaluation and original-head required CI.
