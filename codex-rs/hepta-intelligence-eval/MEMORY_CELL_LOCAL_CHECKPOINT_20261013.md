# MemoryCell local checkpoint — 2026-10-13

This checkpoint records a local validation increment on branch
`codex/memory-cell-evidence-20261008`.

## Environment

The isolated worker environment was created locally at
`/tmp/hepta-memory-python-20261013` with:

- Python 3.12.14
- torch 2.5.1+cpu
- transformers 4.57.1
- peft 0.17.1
- accelerate 1.10.1
- safetensors 0.6.2
- numpy 1.26.4
- huggingface-hub 0.35.3

The repository's `scripts/memory_cell/requirements.txt` was installed without
changing the production runtime.

## Validation

`PYTHONPATH=scripts/memory_cell <venv>/bin/python -m unittest discover
-s scripts/memory_cell -p 'test_*.py'` completed with **1529 passed, 15
skipped, 0 failed** in 56.849 seconds. The focused source-write, projection,
exposure, paired-effects, and strict bottleneck suites completed **53/53**.

The passing tests validate source-only schedule construction, supervised
position accounting, actual input/label binding, write-before-exposure
metadata, parameter-only controls, paired candidate identity, and fail-closed
receipt checks. Fixture outputs remain diagnostics and do not establish task
success, semantic citation precision, or production eligibility.

## Real-model boundary

No Qwen2.5-3B weight files were present in the local cache at this checkpoint.
Therefore no local command claims a real Qwen generation, loss, gradient,
parameter update, throughput, task success, citation precision, or cost. The
pinned Qwen2.5/Transformers/PEFT execution remains gated on the original model
inventory and source SHA receipts; a tiny or synthetic model is explicitly not
a substitute.

`production_accepted=false`, `semantic_citation_precision=null`, and no
promotion or scale-out decision is made by this checkpoint.
