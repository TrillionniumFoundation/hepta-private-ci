# MultiRC three-way factorial seal audit (2026-10-14)

- Parent: #2016 / `6d22d29c666d4ef1ba3ca1f9315b15dc6786e5d4`.
- Draft PR: #2030, branch `research/shared-stem-multirc-three-way-seal-review-20261014`.
- Exact locally and remotely matched tested code: `1295bc003ed1fed423af3e879a1b95883aec0518`.
- No main merge, historical rewrite, threshold tuning, model selection or production deployment.

## Identified gap and repair

The predecessor review was a Python-only function. It did not automatically run
on real hosted MultiRC factorial artifacts or independently check the factorial
byte seal against the frozen model and prior blinded stress evidence. It also
accepted self-consistent but incorrectly aggregated per-row shifts or changes in
its descriptive epsilon. This is now an actionable fail-closed integrity gate.

- Require immutable external factorial, predictor and stress seal IDs. Verify
  each owner's byte SHA256 and schema, reject FAILED, symlinks and mismatched
  source panel/snapshot/Reader weights and ordered task inventory.
- Recompute all three absolute probability means and near-zero question counts
  from the complete 2-by-2 experiment records. Require the registered 0.001
  **descriptive** threshold, original ATen formula cost and no unknown operators.
- Add a required review CLI in the existing hosted canary between blind
  factorial execution and opening held-out label material. Publish `review.json`
  with its own COMMITTED SHA256/ID; preserve FAILED when verification fails.
- No labels are read, no new model is trained. In particular, absolute probability
  shifts cannot reveal signed query-answer interactions or counterfactual labels.
  Do not claim independent quality, statistical superiority or safety approval.

## Actually executed

- 13 focused CPU tests passed twice; one test reloads actual tiny PyTorch-trained
  Reader weights and seals with the original blinded stress / prediction records.
- Complete local **source slice** executed 610 unique tests twice. Both rounds
  had exit code 0 and zero discovery errors, failures, errors, skips or expected
  failures. Test IDs and all 56 test source hashes agree exactly.
- All three uploaded code/CI Git blobs equal the tested local source byte-for-byte.
  Python compilation and workflow YAML parser succeeded.
- This does not constitute a full-repository, Rust/native/GPU or production run.

## Hosted evidence pending

The exact code commit triggered `hepta-real-multirc-reader` workflow
38584542142; its initial source/HF jobs were queued when checked. The upstream
MultiRC pretrained canaries had not yielded a verified new real-model score.
No pretrained conditioned Reader gains, independent source/observer provenance,
actual service costs, energy, NDU/SYSTEM2, multimodal generation or 1024/4096
Cells are qualified here.

## Reproduction

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python qualification/stem-cell-v1/run_checked_tests.py \
  --output /new/nonexisting/checked-tests.json
```

To run the label-free review, invoke `multirc_factorial_review.py` with all
three original owner/factorial/stress directories, their externally captured
COMMITTED seal IDs and an unused output directory. The hosted workflow records
those exact arguments and does not load labels until review completion.
