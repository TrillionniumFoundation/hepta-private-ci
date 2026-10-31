# Post-execution independent checks

These read-only scripts and interpretation notes were produced after the registered bridge experiment. They did not choose its training, evaluation, or acceptance rules. The original scientific source remains pinned in the sibling study's `evidence/SOURCE_FREEZE.json`.

`review_complete_results.py` independently reconstructs this completed reference run's paired arithmetic without importing its analyzer. Its expected protocol constants and negative-result check refer specifically to this registered run. `check_matched_information.py` verifies that methods sharing a generator received identical persisted previews and that identical selected actions produced identical persisted outputs. It also reconstructs recorded timing summaries and reset sensitivity.

```bash
python experiments/multimodal_output_portfolio/field_bridge_20261027_review/review_complete_results.py \
  --run /path/to/extracted/run --out ./arithmetic-review.json

python experiments/multimodal_output_portfolio/field_bridge_20261027_review/check_matched_information.py \
  --run /path/to/extracted/run \
  --study experiments/multimodal_output_portfolio/field_bridge_20261027 \
  --out ./matched-information-review.json
```

The arithmetic script was packaged with explicit input/output arguments after execution; its calculations are unchanged. `PROVENANCE.json` records both source identities. The executed receipts are in the sibling study's `evidence/RESULTS_REVIEW_CHECKS.json` and `evidence/MATCHED_INFORMATION_CHECK.json`. These additional consistency checks do not constitute a replication on new experimental data.
