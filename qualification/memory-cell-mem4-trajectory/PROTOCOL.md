# MEM-4: complete trajectories with matched replay exposure

Scientific decision: HOLD / NoUpdate. This synthetic ordering experiment does
not replace the product's uniform replay or strong retrieval defaults.

MEM-2 branched independent windows from a common parent. This experiment runs
two complete A1 → B → A2 trajectories. The stationary arm carries the state
changes caused by earlier replay order into later phases. Dynamic owner cuts
retain the original reset/rebuild semantics and may erase earlier differences.

An independent no-replay reference freezes each pre-sleep population and its
prediction-derived priority. Both replay arms consume the same full record
multiset, source/version coverage, payload bytes, update-request bytes, 64
updates per boundary and numeric kernel work. Only order differs. Reference
cost is nonzero: its complete reported trajectory cost is charged to each arm.
It is not a claim of equal physical CPU, wall time or memory cost.

Use seeds 0–4, dynamic and stationary conditions, and one reference plus two
replay arms per condition/seed: 30 planned trajectories, 10 matched pairs.
Counterbalance replay-arm execution order by seed parity. The B stable-A panel
is the descriptive retention comparison; preserve every other panel, online
observation, failure, worker restart and cost record. Seeds share a synthetic
generator and are not independent real-task or model-training confirmations.

The reader reconstructs replay request bytes and hashes from retained reference
records, plans and event receipts, and checks provenance and fixed kernel-work
formulas. This establishes retained-evidence consistency, not execution
authentication. Native worker restarts leave the Python owner alive; full-owner
cold recovery and continuous unlearning remain outside this experiment.

Run from the repository root:

```sh
python scripts/memory_cell_mem1/run_trajectory_coverage.py \
  --native /absolute/path/to/mem1_fast_memory \
  --output /absolute/new/campaign-directory \
  --source-revision EXACT_40_HEX_SOURCE_COMMIT --seeds 0 1 2 3 4
```

The manifest binds the supplied revision, all local Python source hashes and
the actual native binary SHA-256. A published execution must additionally
compare those source bytes with that commit. A nonempty failed-run roster must
remain visible and the CLI exits nonzero. Protocol-double tests are software
regressions and are never native retention measurements.
