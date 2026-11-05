# Bounded maintenance for event and affine memory cells

This component extends the v4 **new event and affine types** with a local,
versioned maintenance experiment. It does not modify the static transfer or
joint-language memory artifacts. V3 source and results remain frozen.

## Contract and scope

`v4.typed_lifecycle.TypedMemoryOwner` stores an event memory, a separately fitted
affine program, a current generation pointer, a separate witness, and every
prepared candidate. Event maintenance reconstructs the current records from
the explicitly retained model-plus-residual codec and trains a fresh full-rank
FactorBank for each of five fields. It does not fine-tune an old parameter bank.
The affine program is fitted from new demonstrations when replaced. Its
predeclared family is `slope * gross_pence + bias`; this is parameter learning
within a supplied program family, not algorithm discovery.

The API is:

```python
owner, receipt = TypedMemoryOwner.create(
    root, initial_source, demo_inputs, demo_targets, seed=seed
)
snapshot = owner.snapshot()
owner.read_many(queries, snapshot, mode="parameter")
owner.derive_many(event_ids, snapshot, mode="parameter")
owner.admit_derived(receipt)
owner.append(records, snapshot, seed=seed)
owner.correct(patches, snapshot, seed=seed)
owner.withdraw(event_ids, snapshot, seed=seed)
owner.refit(snapshot, seed=seed)
owner.replace_procedure(new_inputs, new_targets, snapshot, seed=seed)
TypedMemoryOwner(root).recover()
```

Reads bind generation, owner manifest, source frontier, event parameter
metadata, residual metadata identity, and procedure artifact. A result from an
old event or procedure version is rejected by `admit_derived`. Content hashes
alone are not treated as execution evidence: admission executes the current
event-to-program computation again and compares the complete canonical
receipt. Changing a value and recomputing its public hash still fails.

Publication writes and synchronizes a prepared version before updating the
witness and then `CURRENT.json`. A mismatch between current pointer and witness
fails closed. Recovery validates the witnessed models, event source codec,
procedure demonstration archive, delta, and write receipt before rolling the
pointer forward. Witness locations inside the owner directory are rejected
before initialization. The witness remains an ordinary separately stored file;
simultaneous rollback of both store and witness is outside the contract.

Normal parameter serving and completed-publication parameter opening do not
read residual archives, procedure demonstrations, or write deltas. A separate
fresh reader installs a real `Path.open` access guard that denies those paths
in parameter mode, then performs the actual model reads. Publication and
recovery **do** read replay for validation and their work is counted. No claim
is made that a recovery process never reads replay.

This is a bounded POSIX single-writer prototype using file locks and directory
synchronization. It tests process death and store-only rollback. It does not
establish distributed concurrency, hardware rollback resistance, arbitrary
power-loss recovery, or physical removal of withdrawn facts from historical
artifacts. Historical models, residuals, failed candidates, and demonstration
archives remain present and are charged in storage totals.

## Frozen experiment shape

The unified entry point is
`run_typed_lifecycle(protocol, output, source_commit, seeds, development=False)`
from `v4.typed_lifecycle_study`. It writes
`typed-lifecycle-summary.json` and `seed-N/summary.json` under the
`typed_maintenance` stage directory. Its configuration is
`protocol["typed_maintenance"]`:

```json
{
  "initial_fraction": 0.5,
  "correction_count": 8,
  "withdrawal_count": 8,
  "procedure_demo_count": 24,
  "derived_query_count": 24,
  "minimum_parameter_exact": 1.0,
  "minimum_unchanged_retention": 1.0,
  "procedure_absolute_tolerance": 1e-7
}
```

The source order determines every update. The first half of the fixed retail
records is written initially, then the remainder is appended. Eight distinct
fields among the first eight records receive explicit synthetic corrections.
Records 8 through 15 are withdrawn. These overrides test maintenance behavior;
they do not assert that the original UCI observations have been corrected.

The six published generations and seven retained candidates are:

| Candidate | Published generation | Operation |
| --- | --- | --- |
| 1 | 1 | Initial event write and first fitted affine program |
| 2 | None | Full append preparation followed by actual process exit before witness publication |
| 3 | 2 | Successful append, independently trained again |
| 4 | 3 | Eight corrections; process exits after witness publication and fresh recovery completes the pointer |
| 5 | 4 | Eight withdrawals and a clean fit of the remaining events |
| 6 | 5 | Another clean refit, performed between two actual graph hops |
| 7 | 6 | Newly demonstrated affine program; current event model is reused |

There are six real event fitting attempts, five field models each: 30 SVD
calls per seed. Two affine fits require two least-squares solves. Failed
publication training is included. Program truth is fixed at `0.9*x + 25` then
`1.15*x - 40`; two distinct sets of 24 demonstrations use the declared seed
offset. Truth coefficients stay in the external grader plan and are never
passed to an inference request. The model receives only demonstrations at
write time and event addresses at read time.

Every generation queries all original record addresses and all five target
fields. Unwritten or withdrawn addresses must return `None`; live-fact metrics
use their own denominator. Unchanged, previously correct facts have a separate
retention measure. All 24 derived addresses are checked, including every
withdrawn address. Numeric error uses raw pence/items and the declared absolute
tolerance for the fitted procedural result. Parameter and explicit-residual
arms are reported separately.

The actual frozen V3 `GraphExecutor` runs two supplied maintenance ports:
derive a versioned event/program result and admit that result downstream. A
real refit after the first callback makes the second hop reject the old
snapshot. Reusing the old callback rejects before execution. A new graph also
rejects a result from an old procedure, and a current result with a forged
value and recomputed digest. These probes test version propagation; they do
not train a new graph or inspect natural-language holdout text.

## Evidence and cost boundaries

Each seed retains:

- `plan.json`: external source/update/affine demonstration plan.
- `owner/` and sibling `owner-witness.json`: all parameters, residuals, deltas,
  write receipts, prepared-validation receipts, historical versions, and the
  uncommitted append candidate.
- `phases/*.json`: actual addresses, snapshots, parameter and exact outputs,
  derived receipts, and measured scores.
- `processes/*`: exact requests, completed outputs or crash receipts, return
  codes, logs, and observed work counters for actual Python subprocesses.
- `graph.json`: actual graph traces and rejected-hop events.
- `stale-admissions.json`: ten separately executed old-result admissions
  covering five prior generations in both read modes. Historical values in
  these admission probes are never included in a fresh read request.
- `faults/`: retained copies used for pointer rollback, parameter corruption,
  and corruption of procedure demos, deltas, and write receipts.

Ordinary current parameter serving, current model-plus-residual serving,
current procedure replay, and all retained history have separate byte totals.
The minimum serving totals do not include the old versions needed to reproduce
the research history. Research totals include copies, outputs, logs, and
candidate receipts. The shared fixed source and original official archive are
tracked by the enclosing qualification source inventory; they are not hidden
inside parameter serving claims.

Array byte sums and SVD/least-squares work proxies are operation accounting,
not measured peak Python heap use or hardware FLOPs. Candidate preparation
times include fitting and overlap with subprocess and total-stage wall times;
these times must not be added together as independent costs. Independent
auditing can verify stored predictions, arithmetic work counts, bytes, hashes,
and update semantics; it cannot independently authenticate historical timing.

## Development evidence

The primary development run is preserved at
`results/development/typed-maintenance-address-only-8011-8017`. It uses only the
384-record development partition and seeds 8011 and 8017. Its summary SHA-256
is `9b0fbba4d6e8f05d9431be1f99325cea5749a3dfe9ca48264c4987a73892e5b5`.
The supplied commit `4c32ee0f2f030a9d25d025ba1b955eb838ceb70f` identifies the
development lineage. Exact executed Python source bytes are retained in the
run's `source_snapshot/`; uncommitted development files are not retroactively
claimed to have existed in that Git commit.

Both seeds passed all 17 declared maintenance checks. Initial 192 records grew
to 384, then withdrawals left 376 live records. All six versions recalled all
five live fields exactly in both the parameter and explicit-residual arms;
unchanged-fact retention was 100%. After withdrawal, all 40 field reads and all
eight derived reads for removed records returned `None`. The largest affine
absolute error across these reads was below `7.51e-12`.

Each seed executed seven actual subprocesses: two deliberate exit-code-73
writer deaths, two recovery processes, separate fresh parameter and exact
readers, and a fresh parameter reader over a store with a corrupted procedure
demonstration archive. The last read succeeds without touching that archive;
explicit recovery over the same damaged replay fails.
Fresh requests contain only addresses and version tokens. Historical derived
results are rejected by the fresh-reader input validator before it opens an
owner. Five old snapshots per mode remain valid rejection-test inputs because
they contain only version bindings. The ten old derived-result checks run
separately and require a nonempty, complete inventory.

Per seed, the current minimum parameter serving state is **50,601 bytes**;
model-plus-residual serving is **52,510 bytes**. The full retained owner and
witness occupy **438,432 / 438,428 bytes**. All research evidence, including
fault copies and source snapshots, occupies **13,051,049 bytes before the
stage-summary file** across the two seeds. Each seed pays for 30 SVD calls
(work proxy 771,664) and two least-squares solves (work proxy 288). These are
maintenance-mechanism results, not a compression or training-efficiency win.

The earlier run at `results/development/typed-maintenance-initial-8011-8017`
is preserved unchanged (summary SHA-256
`c3aca2f177addbef1b6c4923855dacb4cadd6fcfa58cc708bfd038043a715ff5`). Its
fresh-process requests carried old derived receipts, including historical
numeric values, solely for rejection probes. Those values did not participate
in model reads, but that request is not evidence of an address-only fresh
read. The newer run separates admission probes and enforces the stronger input
boundary. This repair changes no model, training rule, source, quality
threshold, or seed, and the old evidence is not retroactively relabeled.

Standalone execution is development-only. Formal callable execution requires
the literal frozen flag and complete ordered formal seed list before any
source read or directory creation; the unified runner additionally verifies
the exact Git source/protocol freeze. No formal maintenance or held-language
evaluation was run while authoring this document.
