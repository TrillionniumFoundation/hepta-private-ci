# V11 persistent replay maintenance experiment

## Result

Persistent bounded replay reduces interference in this controlled experiment,
but does not solve long-term retention or rejection reliability. All four arms
learn the final batch of eight new records exactly; their old-record retention
differs substantially. Clean reconstruction restores the remaining known
records after corrections and revocations. These are results on random continuous
key features, not natural-language memory, compression, or general-memory results.

The completed run is distributed in the
[immutable maintenance evidence package](evidence/archives/maintenance-v11/README.md).
Restore it to read `v11-maintenance-formal-01/SUMMARY.json` and the complete raw evidence.
It uses three preregistered seeds: 1009, 2017, and 3023. Every attempt, checkpoint,
optimizer state, training schedule, source list, and held prediction is retained.

## Frozen experiment

The archived `PROTOCOL.json` and `SOURCE_IDENTITY.json` were written before
training and are preserved byte-for-byte by the package inventory. The repository baseline is
`740dbff4e00b8b74a19c6b7ec487937c1f4c96ab`; the changed executable files are bound
by their own SHA-256 hashes and copied into the evidence directory.

The model is a 32-input, 64-hidden-unit GELU MLP with 12 binary outputs. It has
2,892 trainable float32 parameters. Training inputs are independent normalized
random feature vectors. Each record has three four-bit values. The initial
stream contains 32 independent and two derived records. Four insert phases add
eight records each. A correction phase changes eight existing values. A final
revocation removes two parent records and their two derived descendants.

Canonical inputs, calibration perturbations, held perturbations, and unknown
query vectors are frozen separately. Calibration and held views concern the
same observed memory keys with independently sampled perturbations; they do not
test unseen entities or linguistic generalization. No held result selects a
training schedule, checkpoint, replay capacity, or hyperparameter.

All arms receive 600 initialization steps. The incremental arms then receive
80 steps per insert phase. The full-active control resets and trains for 900
steps on every insert. Every arm performs a 900-step clean reconstruction after
the correction and after the revocation. The batch size is 16. This deliberately
exposes the cost of a strong complete-reconstruction control; it is not a
comparison with equal total training budgets.

## Results before clean reconstruction

The following are means over the three seeds after `insert-4`, with 66 current
records. “Unchanged” contains 58 records excluding the latest eight additions.
The conditional column is restricted to unchanged records that the previous
checkpoint answered correctly. It is reported alongside unconditional retention
so that prior failures cannot disappear from the denominator.

| Arm | All known held exact | Unchanged held exact | Retention conditional on previously correct | Latest eight exact |
| --- | ---: | ---: | ---: | ---: |
| No replay | 17.17% | 5.75% | 24.12% | 100% |
| Persistent buffer capacity 16 | 40.91% | 32.76% | 64.77% | 100% |
| Persistent buffer capacity 32 | 58.59% | 52.87% | 78.23% | 100% |
| Full-active clean reconstruction | 100% | 100% | 100% | 100% |

The buffer capacities bound the entire persistent hot set, including any newly
inserted records selected into that set. The number of replayed old records can
therefore be below 16 or 32. Actual selected counts are recorded for every fit.

After each mandatory clean reconstruction, all arms achieve 100% canonical and
held exactness on the remaining known records. This does not mean the incremental
arms preserved those records: their weights and optimizer were explicitly reset
and the current evidence was reread. The initial parameter digest is checked
against the declared clean initialization.

## Calibration does not close the held rejection problem

Threshold selection uses calibration data only. It maximizes correct known
acceptances subject to zero wrong-known acceptances and zero unknown acceptances
on that calibration split. If no threshold qualifies, the reader rejects all.

That finite calibration condition does **not** guarantee the same behavior on
held queries. Concrete retained failures include:

- At `insert-4`, no replay with seed 1009 accepts three wrong known answers among
  eleven accepted known queries.
- At `insert-4`, buffer 16 with seed 3023 accepts two wrong known answers among
  twenty-three accepted known queries.
- At `insert-4`, buffer 32 with seed 2017 accepts one of sixteen held unknown
  queries. The full-active control also accepts one of sixteen unknown queries
  in each of seeds 1009 and 2017.
- After correction, every arm accepts one of sixteen held unknown queries in
  seeds 1009 and 3023, despite perfect known-record exactness.

The repeated phases and shared synthetic query identities are not independent
trials. No population error bound or production reliability claim is inferred
from these three seeds. Rejection calibration remains an open blocker.

## Persistence, corrections, and revocations

The SQLite evidence ledger retains versions, explicit sources, derived-record
dependencies, checkpoint ancestry, and tombstones. New training work uses an
indexed durable queue; replay samples only the bounded hot set. The full evidence
archive is intentionally unbounded and is accounted for separately.

Every arm closes and reopens SQLite after the second insert, then reloads the
actual model and optimizer checkpoint. All twelve restarts reproduce the probe
predictions exactly. Correction makes the preceding checkpoint lineage invalid;
the experiment does not bypass that invalidation by relabeling an inherited
model as a clean fit.

Revocation denies both parent records and their derived descendants before model
inference. The same denial survives another close/reopen cycle. Each final
database has 74 archived record versions, 62 active records, and six invalid old
checkpoints. The final clean checkpoint is backed only by current sources. The
two replay buffers remain bounded at 16 and 32 records, respectively.

These are service-denial and clean-reconstruction guarantees within this research
implementation. Historical evidence bytes remain in the archive. The experiment
does not claim physical erasure, mathematical parameter unlearning, or live
Rust owner admission.

## Cost and storage

The incremental arms consume 43,520 sample presentations per seed across the
whole stream, including both clean reconstructions. The full-active control
consumes 96,000. All costs of reconstruction are reported separately.

| Arm | Mean total fit seconds | Mean clean-reconstruction fit seconds | Mean bytes in seven model/optimizer checkpoints |
| --- | ---: | ---: | ---: |
| No replay | 4.46 | 2.89 | 310,011 |
| Buffer 16 | 4.37 | 2.79 | 314,146 |
| Buffer 32 | 5.05 | 3.06 | 317,994 |
| Full-active reconstruction | 11.41 | 9.96 | 323,614 |

The complete run took 85.45 seconds with two PyTorch CPU threads. These timings
come from a shared host and are not a deployment throughput comparison; the
small timing differences among the incremental arms are not evidence of speedup.
The final evidence directory contains 17,234,150 bytes. The top-level summary's
`raw_evidence_bytes` field was measured before writing that summary itself.

Checkpoint, optimizer, archived source, database, feature-bank, and replay bytes
are visible separately. This experiment makes no overall storage-compression
claim. Parameter bytes alone would not be a complete accounting.

## Reproduction

The recorded runtime is Python 3.12.14, NumPy 2.3.5, and PyTorch 2.14.1+cpu.
From `qualification/memory-cell-v11`, with that environment activated:

```bash
python -m unittest -v test_maintenance_evolution.py
python maintenance_experiment.py --output evidence/v11-maintenance-reproduction-01
```

The output directory must not already exist. The script freezes its protocol,
input arrays, input source records, executable sources, and runtime identities
before fitting. Reproduction creates a new run identity and preserves the
original formal run. `RESULT.json`, `PREDICTIONS.json`, `TRAINING_SOURCES.json`,
and `schedule.npy` in each seed/arm/phase directory provide the detailed evidence.
