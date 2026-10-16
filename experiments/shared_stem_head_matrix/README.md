# Cell Head architecture matrix

This research-only runner compares linear, gated, LoRA and sparse-expert
Cell Heads over one frozen shared Stem. It keeps the active Cell workload,
training budget and holdout task set identical. Results are diagnostics;
`production_accepted` and model-selection authority remain false.

```bash
python3 experiments/shared_stem_head_matrix/runner.py --output /tmp/head.json
python3 -m unittest discover -s experiments/shared_stem_head_matrix/tests -v
```
