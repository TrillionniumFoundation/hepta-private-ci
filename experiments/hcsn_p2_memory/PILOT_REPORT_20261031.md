# P2 sampled Brownian FIRE + trainable content state — 2026-10-31

**RESEARCH_ONLY / DENY_ALL / NO_GO.** Stacked on #4500 exact parent `47e8501c3d6a7f08fdd9595c70a2904bf6274688`; retained all earlier P0/P1 negatives. Frozen protocol committed **before the six production-size pilot runs** as `PILOT_PROTOCOL_20261031.json` on commit `0f29a3d0e52cca378c9f8b7e1c6e865e8b6dcf60`.

## Actually added

- `event_content.py` bridges the exact sampled Brownian first-hit / regenerative multi-FIRE oracle from `experiments/hcsn_hx_unified_v3/renewal_spike_sampler.py`, upstream exact Git blob `df65b3b2a167e544b45e0f480a57fbe7a09d725b`.
- Trainable 5,186-parameter 32-unit recurrent content vector, continuous exponential decay in elapsed time, FIRE-count-dependent trainable event transform, and GRU observation writes. The content state survives spiking unless learned otherwise; not a claim about optimal reset. This code **aggregates FIRINGS by observation interval**, without applying the trainable event operator separately at each physical FIRE timestamp.
- `ContentSession` atomically stages Brownian event advancement, content read/write, causal timestamps and budget/error rejection before committing. It serializes float32 content, model weight digest, sampler RNG/pending FIRE, times and counters in one versioned SHA256-checked JSON checkpoint. The digest checks **accidental integrity only**, not authenticity, persistence/journal atomicity, rollback authority, production final-use or host crash recovery.
- `test_event_content.py` has six executable checks: actual trained gradients, correct Selective Copy and four-key overwrite/MQAR labels, irregular time, repeated physical FIRE with bitwise split/full checkpoint equality, invalid checkpoint/time/budget transaction refusal, **fresh Python process** model load/restore and exact final checkpoint equality. 6/6 passed locally without skipping.

## Frozen train/test pilot execution

Python 3.13.5, PyTorch 2.10.0+cpu, one torch thread. Two tasks, three independent seeds, 400 full Adam steps at 24 examples/update, 256 training and 256 ID/OOD evaluation samples each. ID length 16; OOD length 32; independent data seeds. Each sample's physical Brownian timeline includes more than one regenerative FIRE. **6/6 training jobs completed** without dropping a seed.

| Task | ID accuracy (three seeds) | T32 OOD accuracy (three seeds) | Interpretation |
| --- | ---: | ---: | --- |
| Selective Copy, single marker and final query | 99.87% | 95.05% | Learned, but one simple task, no matched tuned baseline |
| MQAR4, four keys, multiple overwrites and four queries | 63.83% | 62.60% | **FAIL** as a strong associative-recall mechanism |

The full six-record raw `P2_PILOT_RESULTS_20261031.json` is in the PR with exact SHA-256 `262156070654bb782c21724345132e20e4361f8eb020dee0f53021c53806ceaa`. New source/test Git blob identities `d180a30b790f516406ff36891e2c5350f8b81973` and `2a82d3fe06beb7e5e414ae58dfed4f26ddf99a71` matched locally executed bytes after GitHub readback. First-seed trained model `.pt` weights are retained as separate downloadable local artifacts, not currently published as Git blobs; every run is reproducible from pinned source + documented seeds. No full repository checkout/CI, GPU, Rust/native owner or physical crash experiment occurred.

## Reproduction

```sh
python -m unittest -v experiments.hcsn_p2_memory.test_event_content
python - <<'PY'
from experiments.hcsn_p2_memory.event_content import train_pilot
for task in ('copy','mqar4'):
    for seed in (0,1,2):
        model, record=train_pilot(task,seed=seed,steps=400,train_n=256,test_n=256,hidden=32)
        print(record)
PY
```

## Strict remaining blockers

**P2 remains OPEN.** Need exact within-interval event application, model-parameter drift/active-set tests, full Selective Copy/MQAR across unseen contexts and data, comparative training CPU/RSS/energy, multiple regenerations with *actual* native owner and durable crash replay, and jointly trained real encoders. P0 full coupled HX is still OPEN; P1 causal financial mechanism benefit remains OPEN (the 80-run pilot has no significant positive comparison); P3 true four-modal remains OPEN; P4 Rust/GPU 64/256/1024/4096+Joules remains OPEN; P5 matched Hybrid remains BLOCKED. `production_activation=false`; `all_scientific_blockers_closed=false`. Keep this a draft PR, not a production merge.
