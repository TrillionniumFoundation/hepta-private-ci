# Archived independent internal acceptance

The reviewer artifacts in this directory are preserved byte-for-byte. They
document a same-session review by a separate agent, not external peer review.
The final gate positive control passes; 121 gate checks and 23 local runtime
checks pass with stable source fingerprints. The initial 113/114 failed review
is retained. These counts are separate from the implementation's 39 unit tests.

[REVIEW.md](REVIEW.md) gives the findings, [CHECKLIST.md](CHECKLIST.md) gives the
acceptance criteria, and [manifest.json](manifest.json) binds the original files.
Its historical reproduction section names the reviewer's original workspace.
For an ordinary checkout, explicitly select the target as follows, using fresh
output files:

```bash
NDU_CONFIRM_ROOT=experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/ndu_llm_confirmation
python "$NDU_CONFIRM_ROOT/independent_review/review_gate.py" \
  --target "$NDU_CONFIRM_ROOT" --execute-after-stable-notice \
  --output /tmp/ndu-independent-gate-new.json
python "$NDU_CONFIRM_ROOT/independent_review/review_runtime.py" \
  --target "$NDU_CONFIRM_ROOT" --execute-after-stable-notice \
  --output /tmp/ndu-independent-runtime-new.json
```

The drivers use synthetic records and local fake workers. They make no external
API calls, reject existing output files and invalidate acceptance if watched
source fingerprints change. Neither a positive synthetic control nor these
checks establishes model identity authenticity, billing authenticity, independent
task benefit or a new RL result.
