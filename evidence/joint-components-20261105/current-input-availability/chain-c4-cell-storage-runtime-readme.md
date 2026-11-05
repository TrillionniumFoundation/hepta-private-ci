# Cell runtime composition and bounded observations

This continuation uses the existing Chain integration PR #688, starting from
`47b4a62463d8e1371a175c74196d52d99c5fccb8` (tree
`c8f3b8e6f5a602edb380f89e1ad941b8d0d374fe`). Protected main was observed as
`dd6e1c3cbeacbdc532b0679297835b3a0aac78f0`. It follows the
[sole plan](../../docs/development/TRNM_AI_NATIVE_BLOCKCHAIN_DEVELOPMENT_PLAN.md)
and [storage contract](../../docs/development/specs/pon/CELL_MODEL_STORAGE_V1.md).

The old residency continuation directory reported in #688 was absent in this
execution environment. These changes were implemented and tested from the
available exact source, not reconstructed by claiming the missing source's
identity or inheriting its earlier test results. The old 272,189,990-byte
cold-transfer failure and unexecuted native model load/query/unload remain open.

## Exact component verification

The implementation was published in `55257c61c46a2687669a0ed6b317b7263db0bd5a`.
The subsequent complete selected verification is bound to committed source
`fc86ed8e927a8eb4e048b160437126a6c0b96c0d` (tree `bd26fb15aa023cbd090662384c25fa52f52b0bc8`). Its original
Cargo graph includes the preserved parallel capacity/ingress and shared-material
changes. The component result is **PASS; product qualification remains HOLD**.
The evidence follow-up preserves later publication base `70df2c644ed8dd64afa1e7533743664cddacb9da`.
Its subsequent PQ source changes are not qualified by inheriting these native
results. That publication base separately passed strict default-feature
workspace/all-target Clippy and the checks command (including 138 Python
controls), with source verified before and after. See its
[checks receipt](publication-70df2c64/cell-publication-checks.json)
and [Clippy receipt](publication-70df2c64/cell-publication-clippy.json).
No native execution on that later publication base is claimed here. The
[publication preservation record](publication-preservation.json) identifies all
72 later parallel path changes and the unchanged non-evidence projection.

| Scope on this exact source | Executed result |
| --- | ---: |
| M09 all targets/all features | 350 passed: 319 library and 31 CLI/other tests |
| M09 expected compile-fail documentation | 9 passed |
| Complete M12 library | 46 passed |
| Original exact M06 capacity/monetary controls | 5 passed |
| Node storage-service owner | 15 passed, including all 6 new complete-release tests |
| Original exact Node Growth activation controls | 2 passed |
| Additional capacity/funding/ingress/lifecycle intersections | 21 passed |
| Original Python controls | 138 passed |
| Additional from-zero/staged/shared-cell Python controls | 140 + 26 + 9 passed |
| Workspace/all-target Clippy, default features, `-D warnings` | PASS |
| Formatting, source pins/inventory, repository links and locked workspace metadata | PASS |

The selected totals are **448 native/compile-fail executions and 313 Python
tests**, with no failed or ignored tests in the completed passing commands.
They do not describe the entire Node suite, fuzz execution, PQ product
qualification, real model execution, or remote CI acceptance. Workspace metadata
has 26 members and 175 resolved packages; no separate fuzz metadata command was
run here. The [verification manifest](verification.json) preserves each command's
exact source, before/after raw-byte verification, environment, result and hashes.
The original 55257 source also completed its 427 selected native/doc executions;
its first ENOSPC attempt remains a separate failed receipt.

The additional 21 native controls cover complete capacity progress (9), new
continuity ranges (2), mandatory-owner ranges (3), two startup owner boundaries,
the existing mandatory-owner funding/refund/maturity test (1), and diagnostic
lifecycle publication (4). These are distinct from the original five M06 and
two activation selectors. Listener-domain exhaustion now intentionally refuses
before waiting for the Node owner; this is not a claim that all ingress error
precedence is unchanged. The [selection manifest](concurrent-regression-selection.json)
lists each original Cargo argv and expected count; actual executions are recorded
separately in the command receipts and the
[execution summary](exact-fc86ed8e/concurrent-owner-executions.json).
The original `reproduce.sh` selects 427 native/doc executions and 138 Python
controls. The additional 21 native and 175 Python results come from separately
recorded commands; 448/313 are aggregate counts, not one invocation of that script.

Native release fixtures contain three synthetic files totaling 651 bytes and
`tensor_model: None`. Complete success/reopen/shared-member cases execute both
AuthenticatedV1 and PermanentAccountGrowthV2; the other new release cases use
GrowthV2. They use development-public Ed25519 identities. Ordinary drop/reopen
and constructed incomplete states do not establish process-crash/power-loss
atomicity, PQ joint qualification or independent custody.

Raw command receipts and logs are retained under
[exact-fc86ed8e](exact-fc86ed8e/cell-runtime-native.json) and
[exact-55257c61](exact-55257c61/cell-runtime-native-retry.json). The large
metadata-bearing checks logs are stored as `.log.gz`; decompressing produces
the original byte stream and receipt SHA-256. No original receipt is rewritten
to name the archive or a later commit.

## Fixed-base space and transfer observations

Each finite cohort has one local base plus eight targets, with a 262,144-byte
payload and 16,384-byte fixed chunks. The nine-copy payload baseline is
2,359,296 bytes per cohort. All 40 delta materializations passed target-byte
and hash readback. Every target directly pins the original complete base;
reconstruction depth is one, without a recursive delta chain.

| Workload | Unique payload bytes | Logical cache bytes | Closed DB/WAL/SHM lengths | Response bytes | Payload saving |
| --- | ---: | ---: | ---: | ---: | ---: |
| identical | 262,144 | 263,515 | 331,776 | 0 | 88.9% |
| single-chunk-sparse-change | 393,216 | 401,715 | 495,840 | 131,144 | 83.3% |
| chunk-reordering | 262,144 | 270,387 | 360,600 | 0 | 88.9% |
| one-to-eight-byte-shift | 2,359,296 | 2,371,635 | 2,536,368 | 2,098,304 | 0.0% |
| dense-full-change | 2,359,296 | 2,371,635 | 2,536,368 | 2,098,304 | 0.0% |

The shift fixture is a same-length circular rotation by one through eight bytes.
Each sparse target independently changes one chunk from the original base. The
shift and dense cases have no payload savings and retain storage overhead.
File lengths are not allocated blocks or peak space; response counts exclude
requests, TCP/IP and local TCX1 recipe/target-manifest distribution. Initial
fixtures, materialized outputs and recipes are outside cache totals. These are
synthetic loopback observations, not a model-corpus or WAN compression claim.
See the [complete observation](exact-fc86ed8e/cell-runtime-workloads.log).

## Changes and boundaries

- Typed resident tensor admission reuses the existing complete safetensors
  parser and payload hash checks. It returns borrowed exact dtype/shape/ranges,
  supports safe cross-chunk F32 reads, and cannot outlive its resident manager.
  Cold misses have no disk or network fallback. This does not install a device
  tensor, authorize FinalUse or execute the real model.
- Complete-release retention enters through the ordinary Node funding owner,
  M12 effect journal and TCA2 root catalog. The root task and each original
  physical member have distinct immutable funding claims. Complete preflight
  grants no authorization; actual mutations repeat their owner checks.
  Pending/Done effects never copy again, repairs require separate original
  funding, and retirement checks the original journal plus the current native
  anchor before rooted GC. Partial state remains charged; no cross-store atomic
  transaction, native coin lock, provider payout or automatic renewal is claimed.
- Original prefetch cancellation now reaches the shared transport owner. A
  session remains cancelled after observing its caller's flag; bytes already
  read stay accounted, and honest peers are not quarantined for local expiry.
  Blocking connect/filesystem/SQLite boundaries remain cooperative.
- Opt-in provider Ready follows reader validation and listener setup. The existing
  handoff script waits for this event inside its unchanged 35-second aggregate window.
  Bounded pipe framing prevents a partial line from adding an unbounded wait.
- A five-workload observer performs actual fixed-base TCX1 retrieval over
  loopback, hashes every materialized target, and independently queries stored
  object counts after closing writers. It reports losing cases as well as
  savings. Its nine-version synthetic cohorts are not a real model distribution,
  a WAN campaign, or a long-term retention observation.

No stored encoding or existing signature domain is reinterpreted. New release
effect subjects/receipts use explicit v2 domains. Existing activation and
qualification flags remain false.

## Reproduce

Use the repository's Rust 1.95.0 toolchain, original Cargo profiles and lockfile,
one Cargo build job, and the complete locked dependency cache. Keep outputs
outside the checkout. The commands are in [reproduce.sh](reproduce.sh).
To reproduce the exact native evidence, first use an isolated checkout of
`fc86ed8e927a8eb4e048b160437126a6c0b96c0d`. Running the commands directly at a later shared
HEAD generates results for that later source; it does not reproduce or inherit
the outcomes reported here. The separate additional command argv are preserved
in the selection manifest and corresponding original receipts.

```bash
set -euo pipefail
export CARGO_BUILD_JOBS=1
export RUSTC="$(rustup which rustc --toolchain 1.95.0)"
cell_source="$(git rev-parse HEAD)"
cell_receipts="$(mktemp -d)"
for scope in native checks clippy; do
  python3 scripts/ci/record_pq_native_command.py \
    --kind head --candidate "$cell_source" --tested "$cell_source" \
    --label "cell-runtime-$scope" --output "$cell_receipts" \
    -- bash evidence/cell-storage-runtime-20261104/reproduce.sh "$scope"
done
python3 scripts/ci/record_pq_native_command.py \
  --kind head --candidate "$cell_source" --tested "$cell_source" \
  --label cell-runtime-workloads --output "$cell_receipts" \
  -- cargo run --quiet --manifest-path trillionnium/Cargo.toml --locked --offline \
  -p trnm-data-availability --example cell_delta_workload_observer
```

`native` includes all M09 library/CLI/example targets, compile-fail docs, the
complete M12 library, and the Node storage-service owner tests. It does not claim
the complete Node/Hepta business suite, all hardware targets, ordinary model
training/inference, or remote CI acceptance. `checks` covers source pins and
negative controls, closed graph metadata, formatting and repository links.

The composition also preserves concurrent `04be5f02` monetary-range and Growth
activation fixes. Five exact M06 conservation/capacity controls and two exact
Node activation controls cover their relevant overlap with the funding owner;
the existing named-libtest checker requires each selected control to execute.

The existing native SQLite build fence requires the absolute canonical compiler
path. Selecting Rust 1.95.0 through PATH alone does not satisfy that fence. The
first development Node build retained its `RUSTC must be absolute` observation;
later runs select the actual compiler without changing the fence or profiles.
Use the ordinary rustup Cargo entry point. Directly invoking the toolchain Cargo
binary omitted one of the original fence's required normal loader directories.
The failed early build was cached; only this checkout's SQLite boundary package
build outputs were cleared before the normal rustup entry passed the original
fence. No loader paths, native compiler flags or acceptance guards were injected.

The `7f766ae8` implementation source passed strict workspace/all-target Clippy
and 138 Python controls. Its native run reached M09 350, docs 9 and M12 46 before
Node test compilation was killed by SIGKILL; the shared cgroup OOM-kill counter
increased from 4 to 5. No Node test ran in that attempt. The source recorder also
lost access to the prior shared Git object directory. All 9,682 indexed source
entries were subsequently restored into this checkout's own object database and
verified against the unchanged `094208d1` tree. These failed/incomplete attempts
remain recorded separately from the composed source's later verification.

## Retained original failure

The first composed 55257 native attempt failed during Node compilation with
`ENOSPC (os error 28)` and executed zero Node tests. Its original-config retry
subsequently passed the complete selected scope. Resource cleanup removed only
rebuildable output; the Cargo profiles, lockfile and original checks were kept.
One later Python invocation used an incorrect dotted-module entry point and
could not import the from-zero driver. The original discovery entry point then
executed all 140 tests, with a separate passing receipt; its failed invocation
and the separately rerun 26 staged tests remain visible.


The new real-TCP cancellation regression was first applied as a test-only patch
to the exact baseline. The original native test exited 101: it observed two
payload requests after the first response set cancellation, instead of stopping
before the second member. This is an actual original-source failure, not an
assertion inferred from static review. The [small reproduction manifest](verification.json)
records the selector, source hashes and result. One older residency test
explicitly required completing all downloaded bytes after cancellation; its
expectation was updated to the new contract while retaining the original
selection, pin, capacity and fresh-session recovery checks. It is not reported
as an unchanged old assertion passing.

## Qualification remains open

The exact original cold-transfer material set, source parent and complete call
record were not recovered from the available workspaces or saved-file searches.
The 272,189,990-byte real model attempt is **NOT_RUN in this continuation**; its
prior first-manifest-header failure at 2.041 seconds and zero consumer bytes
remain open. The aggregate 35-second window is unchanged. A differently sized
research cohort is not substituted for the missing original inputs.


Required external evidence remains: architecture/expert ABI and quantization
policy for a selected real model; ordinary Hepta model load/query/unload under
CURRENT/withdrawal/FinalUse; device/VRAM ownership and reclaim; native locked
funding, sustainable paid renewal and independent holding evidence; mature
discovery/eclipsing resistance; and the original three-independent-operator,
at-least-72-hour WAN retrieval/repair/recovery campaign. No component result
closes these requirements.
