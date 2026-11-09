# MEM-2 source coverage and replay order control

## Question and fixed boundary

MEM-1 found that the registered structured selector lost to uniform replay on
all five seeds in both owner conditions. Structured replay also consumed fewer
distinct sources. Those observations do not identify the cause of its loss.
MEM-2 tests the priority/order rules conditional on **the same native state,
same complete eligible pool, and exactly the same source/version multiset**.
It cannot by itself establish that source coverage explains the historical gap.

The executable uses the existing Rust normalized-delta kernel and the frozen
MEM-1 synthetic facts, feature map, owner transitions and A→B→A stream. It loads
no pretrained encoder or language model. Scientific qualification remains
`HOLD`, and production/shared-model adoption remains `NoUpdate`.

## Four common-state forks

Run the existing `fast_uniform` reference trajectory in the dynamic and
stationary owner conditions. Immediately before its A1 and B sleep boundaries,
retain the native checkpoint and all eligible replay records. Fork four native
workers from exactly that checkpoint. The reference trajectory continues with
its original uniform sleep rule after the forks; no fork output is adopted.

| Fork | Source schedule | Ordering |
| --- | --- | --- |
| `legacy_uniform` | Original sampling with replacement | Original uniform |
| `legacy_structured` | Original four-slot priority selector | Original structured |
| `coverage_uniform` | Common balanced 64-sample multiset | Uniform permutation |
| `coverage_structured` | Same complete multiset | Structured priorities restricted to unspent quotas |

The legacy forks preserve the original **selector rules**, but use a common
parent state. Their outcome is not the full-trajectory legacy retention
reported in MEM-1. The historical MEM-1 results remain unchanged.

In the matched forks every eligible source appears either `floor(64/n)` or
`ceil(64/n)` times. A shared deterministic random permutation allocates the
remainder. The structured rule alternates recency, stored prequential
uncertainty, rare label and A-task rehearsal, choosing only among remaining
quotas. Its uncertainty is fixed before the fork. The selector never queries
evaluation outcomes, future stream observations or future facts.

## Matching and costs

Both matched forks consume identical complete serialized replay records,
including source version, key generation, features, target, age and stored
uncertainty. The verifier checks the exact record multiset, not just the number
of distinct sources. It reconstructs all native update request bytes, and checks
64 updates, 26,624 kernel multiplications and **zero teacher calls/bytes/work**.
The actual command wrapper meters emitted update bytes.

The comparison is teacher-free. It does not qualify the stabilized/teacher arm.
Selector time, native IPC time and window wall time are retained separately;
matching data and kernel work does not imply equal CPU, RSS, energy or monetary
cost. Parent trajectory timing includes these extra forks and cannot be
compared directly to the old MEM-1 timing table.

## Outcome, roster and evidence

The fixed panel contains eight stable-A, two superseded, one revoked, one
out-of-scope and eight paired-constituent queries. The latter does not establish
learned relational composition. Expected answers are reconstructed from the
seeded owner facts and current owner generation, independent of reported score
flags. Every attempted query remains in the denominator.

Default roster: five synthetic stream seeds × two owner conditions × two
boundaries × four forks = **80 native replay windows**, 5,120 replay updates and
1,600 window-panel queries. These are synthetic stream repeats, not independent
pretrained-model training repeats. Report paired per-seed outcomes before any
aggregate; do not turn a descriptive advantage into a product promotion.

Each window retains its initial checkpoint, complete frozen pool, replay order,
support commitments, native state receipts, final checkpoint, raw answers,
accounting and audit. Failures retain their receipts and remain failures.
Source and binary hashes bind the measured artifacts but do not authenticate
the original execution or grant production owner authority.

```sh
python scripts/memory_cell_mem1/run_coverage.py \
  --native /absolute/path/to/mem1_fast_memory \
  --source-revision EXACT_BASE_COMMIT \
  --output /absolute/path/to/new-mem2-output
python -m unittest discover -s scripts/memory_cell_mem1 -p 'test_coverage_control.py'
```

The output directory must not already exist. Preserve the binary's original
source/build provenance when reusing a retained binary. A new native build must
have its own identity and verification record. Production memory policy stays
on the established strong retrieval path; no scheduler promotion follows from
passing this experiment's consistency checks.
