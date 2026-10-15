# V3: physically exercised pinned stock-HF encoder ingress (qualification only)

## What this increment closes

V2 verifies contract schemas and injected backend counters but could not prove
that the configured `LocalEncoder` *actually loads* a model from safetensors,
materializes its weights, tokenizes a batch and executes the frozen backbone.
V3 adds a separate hermetic material-integration suite using an actual stock
`BertModel` + `BertTokenizerFast` saved as local safetensors/tokenizer files.
The checkpoint is **randomly initialized** and intentionally tiny; it establishes
loader/execution contract coverage, **not** pretrained language quality.

The new test suite exercises the production-intended research adapter through
`run_offline` (not a fake backend), verifies forward-call accounting and
create-only receipts, independently recomputes the token-masked mean from the
saved model, compares the exact reloaded output bytes, and ensures altered
weights, changed tokenizer, unlisted checkpoint files, incorrect output width
and over-limit token counts all **reject without writing claimed success**.

## Hosted CI enforcement

A separate `hepta-pinned-encoder-physical-smoke.yml` installs CPU Torch 2.5.1 plus
NumPy 1.26.4, Transformers 4.57.1, safetensors 0.6.2, HF Hub 0.35.3,
tokenizers 0.22.1 and psutil 7.0.0. The workflow explicitly imports
`BertModel`, `BertConfig`, `BertTokenizerFast` and `load_file` before the suite;
the hermetic test cannot be silently skipped due to absent HF dependencies.
The independent physical-smoke workflow does not replace the existing V2
contract workflow. The complete test log, dependency freeze, exact source commit/tree and source
SHA-256s are retained as artifacts even after a failure.

Run locally after installing the *same pinned versions*:

```sh
PYTHONPATH=experiments/shared_stem_cell \
python -m unittest discover -s experiments/shared_stem_cell \
  -p 'test_multimodal_*.py' -v
```

Environments without Transformers may mark six physical tests skipped. Such a
local pass is **not** a physical model load receipt, and the hosted workflow
must not skip any material-integration test.

## Evidence boundary and following gates

- Passing the hermetic physical suite proves loading, file/material matching,
  actual local forward and output pinning for a **synthetic tiny BERT** only.
- A `snapshot.revision` value is a declared material identifier; the test does
  **not** authenticate any remote publisher or checkpoint provenance.
- There remains no executed mmBERT-small or Granite-97M R2 reference, no
  checkpoint hash pin, and no evidence of a matched real-task improvement.
- For an A0/A1 qualification, stage independently verified **real pretrained**
  checkpoints and tokenizer/config manifests; require source-disjoint frozen
  train/calibration/future corpora, identical task/head budgets, fixed pooling
  declarations, true observed CPU/RSS/latencies, frozen no-change baseline,
  evaluator-independent future NDU and OOD/negative-transfer criteria.
- Do not merge the V3 hermetic smoke into activation or mark real models as
  qualified because its tests or CI pass. Rust Worker/zero-copy, NDU owner and
  production final-use authorization remain unchanged and unqualified here.

## Mandatory disposition labels

The CI artifact may report a passed *physical loader contract* only if all six
random-BERT integration cases complete without skips. It must continue to set
`checkpoint_pretrained=false`, `real_mmbert_or_granite_executed=false`,
`real_world_capability_established=false`, and `production_accepted=false`.
A queued or skipped workflow provides no loader-execution receipt.
