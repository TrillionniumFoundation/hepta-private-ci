# Fresh-process boundary recovery result

**Version 2 passed all 505 fresh-process boundary replays.** The first version's
16 strict mismatches are retained as a failed stage. The correction preserves
the archived relative Owner folder spelling in missing-file error strings;
it does not relax comparisons or alter dynamics, head weights, packets,
fees, actions or checkpoints.

| Stage | Published source | Workers / distinct PIDs | Exact matches | Process failures / timeouts | End input hashes |
| --- | --- | --- | --- | --- | --- |
| V1, failed | `56fb94039bea79b72b059c639b61d1f7bbb0b2be` | 505 / 505 | 489 | 0 / 0 | unchanged |
| V2, passed | `866ecf9872c968db55bc12ccf63826b7651c5918` | 505 / 505 | 505 | 0 / 0 | unchanged |

Each version restores every stored boundary of the same 80 archived adapter
episodes / 40 worlds, with a new Python interpreter and newly loaded frozen
head and FullHX content owner for each boundary. Expected suffixes remain in
the parent comparator. The worker actually runs its remaining actions and due
source accesses. Every non-timing decision field and final checkpoint must
match the uninterrupted archived run exactly, including charged costs, observed
history, pending request, continuous voltage/mode/refractory state and PCG64.

Each version made 324 source-access attempts: 308 successful FullHX completions
and 16 failures. Their suffixes contain 92 recorded events; these repeat existing
suffix trajectories and do not create 92 new independent experimental events.
The input cohort remains the prior 40 worlds, not new scientific confirmation.

The first version's recursive failure diagnosis verifies that all differing
non-timing fields are missing-file `error` strings with an absolute path where
the archived Owner used a relative path. Version 2 was independently published
before a complete 505-worker rerun. The first version's failed gate remains
failed; none of its failed boundaries were dropped or relabeled as passing.

| Measured cost, seconds | V1 | V2 |
| --- | --- | --- |
| Execution wall span | 97.711861210 | 164.980002418 |
| Parent process CPU, execution span | 1.827840500 | 1.943040589 |
| Parent entry-to-summary CPU, including imports | 3.373555396 | 3.292208635 |
| All child user + system CPU, including interpreter startup | 243.111157000 | 276.163930000 |
| Sum of worker entry-to-result CPU | 195.332708178 | 215.333169945 |

Failed-stage costs are preserved. The two stages consumed 519.275087 child
user-plus-system CPU seconds in total. Wall measurements reflect the actual
host load and have no speed-advantage interpretation. Parent entry-to-summary
wall spans were 98.561304772 and 166.041324374 seconds respectively. Each worker
also records its own fresh FullHX load costs and subprocess wall duration.

Execution archives use repository-root-relative paths. They contain the source
freeze, STARTED record, SUMMARY and all 505 actual worker request/result
receipts, with failure diagnosis additionally retained for V1:

| Archive | Bytes | Members | SHA256 |
| --- | --- | --- | --- |
| `evidence/continuous_cold_v1_EXECUTION.tar.gz` | 1,473,337 | 509 | `b3d2b62993e5f4bad61732149175b4b2039c13e6966254e03de7d479a3c4fed8` |
| `evidence/continuous_cold_v2_EXECUTION.tar.gz` | 1,473,367 | 508 | `8c8b5103e596448a9fbe2926a0471709af9776bd6f054e72bf1f51da9fc9f620` |

The companion `*_MANIFEST.json` records every member hash. Archive contents were
read back and verified against those manifests. Each receipt preserves the
complete JSON value actually returned on successful worker stdout, stderr and
returncode, plus the input request and measured timing. Successful stdout's
canonical JSON bytes are recoverable from the frozen worker's serialization
format; a separate literal byte stream was not retained. The failure branch
would preserve literal stdout text; neither stage had a failed child process.

The runner binds 325 existing source/model/raw/world files. Declared missing
packet paths are audited separately for absence because an absent path cannot
be represented by an existing-file content hash. The independent audit is an
additional qualification record, not a change to either frozen source.

This closes the declared fresh-Python-process recovery gate at completed action
boundaries, including boundaries with pending requests and refractory state.
It does not cover interrupted in-flight actions, torn durable writes, power
loss, malicious snapshots, exactly-once external side effects, continuous Rust
execution/ACK recovery, task advantage, gradients or production readiness.
Operating-system caches remain available throughout the engineering replay.
