# Separately frozen skill maintenance

This experiment supplements the existing **semantic-only** 64-cycle study.
It does not alter that study's frozen protocol, source files, results, or costs.
It starts from the preserved Formal-01 skill checkpoints and original SQLite
sources, with eight canonical workflow addresses and seeds 731, 732, and 733.

## Registered execution

Every seed receives 64 authored program changes. Each program contains three
bounded operations followed by `stop`. The source mutation chooses the first
program in a predetermined enumeration that changes behavior on at least one
of four public execution probes. It never consults model predictions or scores.
Every eighth cycle also revokes one workflow and trains a clean replacement
from the retained untrained initialization over the seven surviving sources.
The following cycle reintroduces that workflow with a new content-bound source
identity and version. The last deletion remains inactive at the horizon.

The fixed budget is 192 update fits plus 24 clean rebuilds, each with 600 steps,
batch size 32, learning rate 0.01, and complete current-source replay. All 216
fits retain their checkpoints, requests, outputs, actual schedule digests and
matching 600-by-32 little-endian int64 schedule bytes. Three initial and 216
post-fit reads run in separate processes; a trainer must exit before its reader
starts. All intermediate phases and failures are retained.

The parameter arm cannot read `sources.payload`. The exact-SQL arm reads the
same immutable SQLite snapshot. Both arms use the same public interpreter.
For each returned program they execute all four probes and retain the complete
status, output and opcode trace. Scoring checks exact program recovery and
exact execution independently. Source changes, revocation and owner stop are
also tested for refusal before any model forward or explicit value read.

The manager knows the authored source state. The fresh reader accepts only
artifact paths and identities; it imports no manager, target generator,
trainer, or evaluator. An independent auditor decodes the saved tensors as
NumPy arrays and independently interprets programs rather than importing the
runtime or training implementation.

## Source and input identity

[LONGRUN_PROTOCOL.json](LONGRUN_PROTOCOL.json) and its adjacent SHA-256 file
register the full schedule before any formal run. `RUN_REQUEST.json` binds that
protocol and the original Formal-01 archive. CI records its actual Git commit,
tree and workflow bytes, verifies the original archive, and retains a separate
`FREEZE.json` inventory for all executed research and monitor source files.
The historical trainer clock is not compared with the new runner clock.

The CI workflow is
[memory-adapter-skill-longrun.yml](../../../.github/workflows/memory-adapter-skill-longrun.yml).
It preserves a filename-safe original TAR plus packaging receipt on success
or failure. Downloaded evidence uses explicit path mappings; original requests,
receipts, parameter files and source snapshots must never be rewritten.

## Interpretation and costs

Execution integrity and scientific quality are separate outcomes. A complete
run can be valid while program or execution accuracy is below 100%. No result
permits retuning the fixed budget, selecting a better intermediate checkpoint,
or omitting a failed phase.

This is a bounded test of full-replay maintenance at known addresses. It is
not open-world skill acquisition, general program synthesis, a capacity-growth
test, a topology experiment, or native Agentd execution of the residual model.
The original Hepta V9 native tests remain a separate execution route.

Costs include training and reader processes, startup, source snapshots,
historical checkpoints, raw schedules, and sampled RSS/PSS/storage intervals.
The encoder is referenced but not reexecuted. Nested CPU scopes must not be
added together. Checkout, Python setup and upload CPU remain outside the exact
accounting envelope; incomplete sample intervals stay unknown. Historical
weights remain available for audit, so deletion is current-service revocation
and a retained-data rebuild rather than physical erasure.

## Evidence status

The formal skill run completed successfully on 2026-10-28:
[run 40742088819](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40742088819),
job `123006077672`, source `4693e8028fb8563ec730dcb55458a212389154a5`.
Its original GitHub ZIP and nested TAR identities were verified, and all 4399
regular output files are retained. The [archive guide](evidence/longrun64x3-skill/README.md)
provides exact identities, restoration commands, quality and cost boundaries.

The run completed 192 cycles, 216 fixed-budget fits and 219 fresh readers.
Both parameter and exact-SQL arms recovered 1512/1512 active programs at cycle
ends, including 207/207 changed and 1305/1305 retained programs, with 24/24
revoked requests refused. Exact execution status, value and complete trace on
all four public probes achieved the same counts. The
[independent audit](../evaluation/AUDIT-skill-longrun.json) passed 28467 checks;
these are checks on one finite experiment, not independent trials or evidence
of superiority over SQL.

The first audit invocation failed while serializing an oversized detail part.
Its complete partial output is [preserved](../evaluation/skill-audit-serialization-failure/README.md).
A skill-specific output writer fixed only report splitting; all comparisons,
thresholds, runtime source files and original evidence stayed unchanged. The
second invocation completed without any fit rerun. Source identities and both
attempts are retained, including the post-formal serializer change.

The disjoint observed wrapper-plus-packaging CPU total is 785.766679218 seconds.
Nested worker/manager/monitor CPU scopes must not be added to it. Resource
sampling retains explicit unknown intervals, and `full_cost_exact=false`
remains. This result establishes bounded skill maintenance at known addresses;
it does not close the residual model's native Agentd integration boundary.
