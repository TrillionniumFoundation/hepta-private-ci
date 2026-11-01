# R16 support-preserving and event-anchored retention

This study extends eight frozen R15 fits with 2,048 fresh owner worlds and ten
candidate arms. It adds an explicit active/recovery by content compression and
an event-anchored filter that does not reproject at arbitrary unobserved time
subdivisions. The model remains a finite synthetic CTMC with supplied addresses.

## Results

- Finite support, independent ODE checks, event-anchored time partition and the
  four registered `.01` quality noninferiority bounds passed in their scopes.
- Persistent numeric state decreased from **1,288 to 296 bytes**, a **77.02%**
  reduction. Model, cache, temporary forty-state propagation and process memory
  are additional costs.
- The original HX core-gain gate did **not** pass: D−B was `+.000503296` in IID
  and `−.000291073` in OOD. D and same-matrix HMM had identical full query traces.
- Anchored/D online CPU ratios were **0.992488 / 1.049554**; complete-cost ratios
  at 1,000 reuses were **0.998161 / 1.012110**. The `.90` cost gate did **not** pass.
- The old mean candidate failed on **21/2,048** attempts. Its quality summaries
  are null in both domains. All other nine arms completed all 2,048 attempts.
- Overall blockers remain open; production activation is false.

Read the [Chinese report](REPORT_ZH.md), [machine blocker ledger](BLOCKERS.json),
[registered protocol](PROTOCOL.json), [final statistics](results/SUMMARY.json),
[support proof and limits](SUPPORT_PROOF.md), and
[independent raw audit](results/INDEPENDENT_RAW_AUDIT_V2.json).
The separate [reachable-joint study](REACHABILITY.md) is finite development
evidence, not the formal fit confirmation or proof that forty-dimensional state
is necessary.

## Exact source and environment

The R15 base is `74144a3f5d5c77c953ecdc4708d3d90b56b67d3c`.
Formal source was published before opening new confirmation worlds at
`01224c2b6ed609fe828f0c6e561b07497aaa7fa1`.
[SOURCE_MANIFEST.json](SOURCE_MANIFEST.json) binds 36 source/model/receipt
identities; [PUBLICATION.json](PUBLICATION.json) records readback of 15 published
files. The manifest SHA256 is
`e8a167247efacfed7463ad1cc86e1457d8833d850d9be3cc349de19cfd9f3f8a`.

Use Python 3.12 and the measured NumPy/SciPy versions:

```sh
python -m pip install numpy==2.3.5 scipy==1.17.0
```

Complete child-process metering uses Linux `wait4`. The numeric modules do not
claim GPU or power measurement. [ENVIRONMENT.json](ENVIRONMENT.json) records the
absence of a CUDA device and powercap energy files in this run.

## Audit the delivered evidence

From the repository root of the delivered revision, with all published raw
archives and inherited R15 inputs available:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m tools.hcsn.support_retention_r16_20261101.audit_results \
  --output /tmp/new-audit.json
```

Choose a new output path if that file exists. The auditor refuses overwrites and
does not import the experiment executor, planner, world or summarizer. Its scope
and preserved audit revision are explicit in the report. Existing published
results should be audited directly, not overwritten by rerunning the campaign.

## Replay the frozen campaign in an independent worktree

Run the following from the delivered checkout. `delivery_commit` captures the
current delivery revision, which contains `PUBLICATION.json`. The independent
worktree starts at the exact experiment-source freeze, whose confirmation output
paths are unused. Use a new worktree path if the example already exists.

```sh
delivery_commit=$(git rev-parse HEAD)
replay_root=/tmp/hcsn-r16-replay
git worktree add --detach "$replay_root" 01224c2b6ed609fe828f0c6e561b07497aaa7fa1
git show "$delivery_commit:tools/hcsn/support_retention_r16_20261101/PUBLICATION.json" \
  > "$replay_root/tools/hcsn/support_retention_r16_20261101/PUBLICATION.json"
cd "$replay_root"
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m tools.hcsn.support_retention_r16_20261101.supervise --workers 2
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m tools.hcsn.support_retention_r16_20261101.statistics
```

The frozen worktree must include all source and inherited input paths listed in
`SOURCE_MANIFEST.json`; verification fails if any are missing or differ. Worker
claims, logs, raw archives and summaries all use create-only output. Do not
delete or overwrite an existing run to make a replay proceed. Use another
independent worktree instead.

This reuses the original model selections and namespace. It is reproducibility
replay, **not a new scientific confirmation**. A changed algorithm, task,
parameter family or namespace needs a separately published protocol and source
freeze before new outcomes are opened.

## Resource and recovery scope

All sixteen confirmation child processes completed successfully. Complete child
CPU was **313.038601 seconds**; original frozen training outer-process CPU was
**30.111223 seconds**. Failed candidate attempts are included. Development and
audit internal CPU are recorded separately and are not complete project cost.
Numeric CPU seconds are not joules.

Each episode performs a real disk checkpoint and restore after query 2. The same
process retains law and transition caches; no action is pending. This qualifies
that declared memory boundary, not cold-process or production owner recovery.
Learned semantic addressing, real multimodal binding, continuous free-boundary
optimality, production Rust ownership, GPU and energy admission remain open.
