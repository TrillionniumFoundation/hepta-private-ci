# Cell Meta Network observed-work frontier (SHADOW / DENY_ALL)

This is a **source-bound resource-accounting diagnostic**, not a new Trainer,
NDU Evaluator, model selector, CAS owner or execution authority. It extends the
five-arm source-correctness analysis and original-source paired screen without
changing any of their historical records or model/Head weights.

## What the new reviewer actually establishes

Given all 3 registered seeds and the exact create-only files already generated
by the existing real-Granite research workflow, it first reruns the entire
independent five-arm source/FP32/route audit and the same-article paired score.
No cost comparison is emitted if one source group, Head tensor, route, split,
prediction or original-source paired report fails its existing checks.

Then it enforces for each non-frozen arm (with `s` SGD steps, `n0` old fit
rows, `n1` new fit rows and `ne` scored evaluation rows):

- Primary train Head rows = `s * (2*n0 + n1)`, with exactly one expert selected
  for every fit row in the *hard-trained* research path.
- Scored inference Head rows = `ne`.
- Parent-loss and Brier diagnostics = `2*(n0+n1)` Head rows, plus
  `2*n0` extra Head rows after split for parent/child parity.
- The split Router requires `s*(n0+n1)` training rows, `ne` inference rows,
  and `n0` diagnostic rows, independent of whether its logits are fixed.
- A trained stochastic Router additionally samples exactly `s*(n0+n1)`
  routes and performs `s` Router optimizer updates, when actually split.
- Two FP32 Heads and their gate occupy `3*(feature_dim+1)*4` **weight bytes**,
  not a process peak-RSS measurement; dormant slots are not silently free.
- The frozen stage-one control **reuses** `s*n0` original fit Head rows,
  incurs zero stage-two optimizer or Router work, and scores exactly `ne` new
  Head rows. Its reused stage-one training is never assigned zero cost.

All counters remain *original-producer claimed observations checked for
internal arithmetic and numeric replay*, not independently signed hardware
measurements. Full-tensor forward/backward FLOPs, wall-clock timing, IPC,
activation and optimizer memory, model-load RSS, energy, target-host p99,
training search failures, NDU evaluation, original Worker signatures,
CAS/Final-use/CNS/WAL/recovery are **not measured** by this path. Such values
are deliberately listed as **unmeasured**, never zero or guessed.

## The distinction this fixes

Equal primary Head rows **do not imply equal compute**. At 64 old + 64 new
fit rows, `s=3`, 256 scored rows, for one synthetic conditional seed:

| Strategy | Primary Head rows (including reused stage 1) | Extra diagnostic Head rows | Router training rows |
| --- | ---: | ---: | ---: |
| Truly frozen | 448 | 0 | 0 |
| Unsplit continued update | 832 | 256 | 0 |
| Fixed Top-1 | 832 | 384 | 384 |
| Learned Top-1 | 832 | 384 | 384 |
| Adaptive split (triggered) | 832 | 384 | 384 |

For a non-triggering Adaptive Split, its Router costs are zero, while it still
pays the original parent diagnostic work. The learned Top-1 Router also pays
stochastic sampling and gradient computation absent from the fixed rule.

The counts above are a local synthetic test, **not** a real 97M Encoder
benchmark. The three training seeds reuse original source rows; the cost
reviewer never triples the count of unique original observations or treats
three correlated seeds as independent future data. In the real Granite job
all arms borrow a shared 224-row feature table. A shared table is not an
independently signed proof of 224 actual hardware forwards.

## How to run

From the repository root, after the real/frozen/paired source reports have
been written create-only:

```sh
python -m unittest -v \
  qualification.cell_meta_execution_af.physical_router_cost_frontier_tests
python qualification/cell_meta_execution_af/physical_router_cost_frontier.py \
  --bundle-dir /path/to/paired-report-directory \
  --out /path/to/new/observed-work-frontier.json
```

The result uses `hepta.cell-meta-observed-work-frontier.v1`. Always record
`full_lifecycle_cost_matched=false`, `all_costs_independently_attested=false`,
`actual_future_outcomes_verified=false`, `statistical_or_resource_winner_certified=false`,
`production_admission=BLOCKED`, and `authority_posture=DENY_ALL`.

## Next acceptance required

1. **P0** Obtain exact-head hosted source/base-merge native and scoped tests,
   correct real failures without lowering gates. The inherited Granite offline
   YAML previously included a broken blank line after a backslash continuation
   in `py_compile`; this candidate removes that source defect. A source fix is
   not a completed GitHub Actions result.
2. **P1** Retain genuine pinned Granite Encoder forwards, original-case
   Q24 feature identities, all five arms and independent per-case replay.
3. **P2** Run a matched-lifecycle resource study with measured Encoder,
   optimizer, Router, failed proposals, source reads and final host telemetry.
4. **P3/P4** Independently observed chronological future utility, NDU/negative
   transfer, and original signed physical split/CAS/CNS/Final-use recovery.

No promotion, selection, merge, or model installation is authorized by
these observed-work diagnostics. `main` and all production Rust modules remain
unchanged.
