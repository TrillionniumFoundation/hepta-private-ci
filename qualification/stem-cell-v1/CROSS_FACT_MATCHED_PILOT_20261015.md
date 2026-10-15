# Matched cross-fact Reader: actual synthetic CPU diagnostic (2026-10-15)

Status: **DRAFT / SHADOW_ONLY / DENY_ALL / no pretrained benefit established**.

## Source and original model
- Exact untouched upstream `token_reader.py` Git blob: `ca814a855c35e3d6fcf50883dba6d66b325d5c54`.
- New `cross_fact_bridge.py`: fact-to-fact attention over masked fact summaries before the existing recurrent Reader. Equal-parameter local MLP is the comparator.
- Base Reader starts with byte-identical initial weights in both arms for each seed. Six public model arguments are unchanged; no labels or world identities enter inference. Four bias-free H×H weights in each arm: 4,096 additional parameters when H=32.
- The pilot below uses **H=16**: 1,024 additional parameters, 7,842 total trainable parameters in each arm; these figures must not be confused with the original 38,466-parameter V5 H=32 Reader.
- No original Encoder weight is updated, installed or physically forwarded by this pilot. No real Granite97 features are used.

## Real local execution

Python 3 with PyTorch `2.10.0+cpu`. Original Reader Git blob was independently checked against the repository. New model/test bytes were separately checked against the pushed Git blobs.

The source tests ran `10/10` under ordinary Python and `10/10` under `python -O`, zero skips. They check the actual six-tensor inherited Reader, parameter parity, nonlocal gradients, padding isolation, actual AdamW parameter updates, bounded attention matrix construction, nonfinite rejection, and independent symbolic truth reconstruction.

The separate actual training program `cross_fact_pairworld_pilot.py` ran all **700 updates per arm per seed** using AdamW, batch size 64, exactly matching sampled rows and example counts. It includes training, evaluation and optimizer state accounting. Training samples contain 16 unique symbolic task combinations, repeated 8 times; evaluation repeats **those same 16 semantic combinations** three times under independently shuffled fact order. This is *not* an independent held-out source family, not novel-vocabulary transfer, and not an OOD/real-natural-task score.

| Seed | Cross-fact correct/48 | Local correct/48 | Cross CPU sec | Local CPU sec |
| --- | ---: | ---: | ---: | ---: |
| 41 | 48 | 36 | 3.548 | 3.555 |
| 47 | 24 | 24 | 3.420 | 3.313 |
| 53 | 48 | 36 | 3.774 | 3.230 |

Each arm completed 44,800 training-row exposures per seed; observed optimizer tensor bytes were 62,824 for both. The sample stream digest matched within each paired seed. Cross-fact computation is quadratic in number of facts, unlike local MLP computation; equal parameter count and updates do **not** mean equal FLOPs. CPU timings are local measured prototype values, not target-host p99 nor complete Encoder lifecycle.

Across these correlated 48-row permutation panels the descriptive pooled difference is **+24/144 predictions** in favor of cross-fact, with one entirely failed seed. There are only 16 semantic combinations, not 144 independent task types. There is no justified inference of natural reasoning improvement, NDU advantage or production selection.

## Reproduction from repository

```sh
PYTHONPATH=qualification/stem-cell-v1 python -m unittest \
  test_cross_fact_bridge test_cross_fact_pairworld_pilot -v
PYTHONPATH=qualification/stem-cell-v1 python -O -m unittest \
  test_cross_fact_bridge test_cross_fact_pairworld_pilot -v
PYTHONPATH=qualification/stem-cell-v1 python \
  qualification/stem-cell-v1/cross_fact_pairworld_pilot.py
```

The pilot emits machine-readable JSON containing every seed, correctness, optimizer storage, CPU/wall cost, training stream identity and explicit nonclaims. Timing numbers vary by host; this is not a signed independent execution observer.

## Next non-negotiable gate
Re-run both arms with the unchanged original V5 Granite97 cache and preregistered paired-world groups, then test fresh source-disjoint combinations and vocabulary without changing the gate based on diagnostic outcomes. Require full four-member world-group fit, natural-task retention, latency/RSS and equal-life-cycle-cost comparisons before any Reader or NDU model selection. Keep the existing negative V5 results and all three split candidates rejected until independently displaced by genuine new evidence.
