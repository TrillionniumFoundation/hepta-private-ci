# MEM7: one observed 4096-record capacity run

**Engineering result: PASS. Scientific qualification: HOLD / NoUpdate. New real confirmation tasks: 0.**

This record measures the public Python `EpisodicStore` implementation at the
4096-record bound on the exact source in [PR #5814](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5814).
The implementation already contains the descendant traversal from #5798. This
change adds evidence and the exact measured harness; it does not change the store.

## Fixed identity and workload

| Item | Identity or value |
| --- | --- |
| Source commit | `4c3b1fb6d40de7c85aedd1964357e138fc7aa9d8` |
| Source tree | `494fe36854e8d26cd9ae0b510e429fe931cef63d` |
| Source path | `scripts/ndu_real_runtime/episodic_memory.py` |
| Source Git blob | `0294daca0a0dee3221be4dc94d563b6816156da1` |
| Source bytes / SHA-256 | 21,522 / `1afcc4a3b3f2b5dbbb0150a97d7513daad4e7226982576f600ae639bef787440` |
| Harness bytes / SHA-256 | 9,895 / `867d8be685c3996ed99d17f9a2ff019801d1ffe79763e4a627bd62f91be75b92` |
| Runtime | Python 3.14.4; Linux 7.0.0-38, x86_64, glibc 2.43 |
| Data and independent unit | One synthetic fixture, one namespace, one source group, one run |
| Shape | One root and 4095 edges in a reverse-key-ordered chain |
| Population path | 4096 sequential public `EpisodicStore.put` calls |
| Limits | 4096 records; 16,777,216 logical serialized bytes; declared wall budget 1200 s |

The record limit was reached through public writes. The initial live view held
4096 records at generation 4096, using 2,996,160 logical serialized bytes. The
exported snapshot was 2,004,986 bytes. Those byte counts describe different
representations and should not be substituted for one another.

The update and revoke arms used separate SQLite backups of the same populated
seed. They share its authority identifier and synthetic data. They are two
operations in one experiment, not two independent trust domains or confirmation
tasks. The original seed view was checked unchanged after both arms.

## Observed result

| Operation | Wall seconds | CPU seconds | Live records afterward | Generation | Old snapshot records rejected | Fresh reader |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Update root | 0.109561283 | 0.106026651 | 1 replacement | 4097 | 4096 | Exit 0; empty stderr; same outcome |
| Revoke root | 0.104260805 | 0.100656627 | 0 | 4097 | 4096 | Exit 0; empty stderr; same outcome |

The revoke receipt's affected-ID set was checked against the entire original
4096-record inventory. Both in-process snapshot reads and both fresh Python
processes rejected all stale snapshot records. Each mutation advanced the
authority generation exactly once. Source and harness hashes were checked
unchanged at the end.

Public population took **175.493080773 s**. The harness wall interval was
**176.297360046 s**. The OS reported **169.074130 s self CPU**, **0.218109 s child
CPU**, **66,076 KiB self peak RSS**, and **61,184 KiB child maximum RSS**.

`EVENTS.jsonl` contains progress observations every 512 writes and the final
complete event. Its 2048-record event, for example, is a point inside this same
4096-record run, not a separate 2048-record benchmark or independent repeat.
No comparative speedup or statistical performance estimate is established.

## Measurement boundaries and raw metadata correction

The raw `RESULT.json` is preserved byte for byte. Its generic
`cost_scope.excluded` text lists interpreter/import startup as excluded. That
exclusion applies **only to the wall timer**. The cumulative `getrusage` CPU and
RSS fields include process startup and imports. This clarification supersedes
the ambiguous wording without rewriting the observation.

- Wall timing starts at harness `run()` entry and ends after checks and the final
  source reads. It includes population, snapshot creation, SQLite backups,
  mutations, two cold reader processes, and source integrity checks. It excludes
  upload, interpreter and top-level import startup, final result serialization,
  and transport.
- Mutation wall and CPU deltas surround the mutation call. Snapshot validation
  and fresh reader recovery are outside those short mutation intervals and are
  inside the overall harness wall interval.
- Self CPU and RSS are cumulative OS process observations. Child CPU includes
  the two readers and any platform helper child. The Linux child RSS value is
  the largest child's peak, not summed concurrent usage. Do not add self and
  child RSS peaks as if they were a simultaneous system peak.
- `EVENTS.jsonl` records the complete event after final result serialization,
  so its final wall/CPU samples differ slightly from `RESULT.json`.
- Energy, full physical cost, model cost, transport cost, and independent
  per-phase allocation peaks were not measured. Unknown costs remain unknown.

## Raw artifacts and readback observations

`RESULT.json`, `EVENTS.jsonl`, both reader stdout/stderr pairs, and
`mem7_capacity_probe.py` retain the exact observed bytes. `MANIFEST.json` pins
each file by byte count, SHA-256, and Git blob hash. The original snapshot and
SQLite databases are not included; their identities and checked receipts are
recorded in the result. Authority identifiers vary on replay, so byte-identical
replayed snapshots or receipts are not expected.

The implementation upload was independently read back before launch. A separate
harness file-info request failed with a closed SSH connection; the actual
launcher subsequently hash-checked the complete harness before compiling it,
and the harness checked the implementation before loading it. Two read/status
requests timed out during a transport outage. A later read-only readback
returned all six output files and verified their sizes and hashes. That readback
was per-file rather than an atomic multi-file snapshot. No benchmark
was restarted to recover those files. The complete event and returned shell
prompt were also observed. The main process exit status was not separately
captured; only the two reader exit codes are explicitly recorded as 0.

Private host paths, transport operation identifiers, and unrelated dispatch
records are intentionally outside this publication.

## Reproduce the engineering check

Use a Linux Python environment and the pinned implementation in this branch.
From the repository root, select a fresh output directory:

```sh
mem7_run_parent="$(mktemp -d)"
python3 -I -B qualification/memory-cell-mem7/capacity-4096-20261111/mem7_capacity_probe.py \
  --source scripts/ndu_real_runtime/episodic_memory.py \
  --output "$mem7_run_parent/result" \
  --wall-budget 1200
```

The harness rejects another implementation hash and an existing output directory.
The declared wall budget is checked during population; it is not an external
hard timeout for every operation. Each fresh reader has its own 60 s timeout.
This publication does not rerun the experiment or claim another sample.

## Remaining boundaries

This measures a chain with at most one dependency per record. It does not cover
the allowed 32-dependency dense graph, independent owner trust, malicious owner
rollback, full external-effect owner cold recovery, ordinary Rust product
integration, real task memory benefit, or all required repository CI. Existing
hosted CI for #5814 is a separate observation. None of these boundaries is
closed by this record, and adoption remains `NoUpdate`.
