# learning.plasticity adversarial follow-up — 2026-10-01

## Result and scope

Detailed development documentation exists. `TECHNICAL.md` specifies algorithms,
typed contracts, authority separation, authentication and recovery requirements;
`OPERATIONS.md` supplies deployment and recovery procedures;
`CURRENT_IMPLEMENTATION.md`, `IMPLEMENTATION_MAP.json` and `CURRENT_STATE.json`
distinguish implemented source from target architecture and acceptance. This
follow-up updates those boundaries rather than treating design prose as shipped
product functionality.

The starting PR head is `ca40d94a5f2bdf9cb8f302d7fcc05fc7d1d200cb`, following the
[first audit](ADVERSARIAL_AUDIT_20260930.md). The main baseline remains
`a126987b84737dbc2ee2592442a314117bddb4a2`. Separate reviews examined lifecycle,
time, live registry integrity, adapter error propagation, documentation and CI.
New findings caused additional implementation and review passes.

## Confirmed findings and corrections

| Finding | Consequence | Correction |
| --- | --- | --- |
| Newly added Agentd tests imported an undeclared `pretty_assertions` dependency | Agentd qualification failed during lib-test compilation, before clock/process checks executed. | Use the standard assertion macro; do not add a dependency or alter the lockfiles. |
| Final proposal admission did not recheck local fencing, draining, cancellation and the original owner epoch | A request could lose admission during preparation, or an old owner could adopt a newer Running epoch. | Pin checked `spawn_generation + 1`; recheck exact readiness/epoch and cancellation at final admission; retain the local lifecycle mutex through the synchronous durability/anchor transaction. |
| Time rollback was checked only within a single request | A rejected expired/revoked request could be retried after the next request's clock moved backwards. | Retain every successful clock sample as an owner-lifetime high-water mark, including samples from rejected attempts; failures do not erase it. |
| Draining was represented by reopenable readiness/lifecycle fields | Late readiness and stale Fleet history could reopen admission in a process that had already begun draining. | Latch draining irreversibly for that process; enforce it in readiness and final admission. |
| Cached registries did not authenticate live file bytes | Truncation or same-length header/frame/checksum tampering could still produce positive cached reads, retry receipts, anchors, canary plans and new append receipts until reopen. | Stream the exact retained header, each trusted frame body digest/footer, length and EOF before positive observations and after synchronized new writes. Any detected corruption or I/O uncertainty permanently poisons the handle. |
| The external shared anchor journal had the same live-file blind spot | After a valid fence/anchor, deleting all journal frames still allowed an identical anchor acknowledgement from cache; corrupt history could also receive a successful new anchor/fence. Both parameter and topology wrappers propagated that acknowledgement. | Authenticate the retained header and trusted fixed-frame history before fence issuance and every anchor acknowledgement, including identical retries, and after synchronized writes; retain poison on corruption or I/O uncertainty. Cached snapshot getters explicitly grant no live-history certification. |
| Adapter health did not consistently reflect registry poisoning | Parameter append corruption and readonly corruption could leave writer health displaying Healthy although the registry was blocked. | Classify corruption as poison and combine writer state with the registry's cached poison latch for both parameter and topology writers. Health getters do not rescan the file. |
| Adding full-history validation after the final clock sample recreated a substantial preparation window | Up to 512 MiB/256 MiB of history could be scanned after evidence time/lifecycle admission. | Prepare and validate the append first, then invoke a final-admission callback before poison/write transitions or an Unchanged receipt; product adapters perform final temporal checks inside that callback. |
| CI process-deadline tests assumed stable `/proc` observations and identical PID namespaces | A disappearing process raised an uncaught `ProcessLookupError`; container namespace mismatch could mistake an unrelated live PID for the child. | Have the child expose its actual `/proc/self/stat` identity, monitor that process/start-time, handle only expected disappearance errors and preserve failure for a genuinely surviving original child. Production executor code is unchanged. |
| Scoped lint helpers forwarded a literal `{args}` token | The repository's `just fix`/`clippy` recipes could not correctly pass package and lint options. | Use the already configured positional `"$@"` forwarding in those two recipes. |

Live-file corruption was reproduced against the previous actual source before
the integrity fix: cached retry, anchor and new append still succeeded, while
anchored reopen rejected the same damaged image. The regression matrices cover
truncation, partial header/frame, same-size header/body/footer mutation and extra
suffixes at all positive registry boundaries, retaining the entire damaged byte
image on rejection. Shared queries serialize their cloned file cursor; safe Rust
exclusive mutable ownership prevents overlap with an append.

The parameter and topology wire/digest formats remain unchanged by this
follow-up. Existing append entrypoints retain their signatures and delegate to
guarded variants. The two public writer `state()` methods intentionally cease to
be `const fn` so they can observe the atomic poison latch; ordinary calls remain
valid, but an external const-context caller must change. No such repository
caller was found. The previous audit's canary V3 signature migration still applies.

## Position in the complete project and completion assessment

| Responsibility | Assessment and optimization boundary |
| --- | --- |
| Native proposal engine (`hepta-plasticity`) | Substantial deterministic, bounded parameter/topology generation and persistence implementation. It depends only on `hepta-types`, grants no mutation/selection authority, and remains appropriately small in dependency scope. |
| Product authentication (`hepta-intelligence`) | Generator/Observer/Evaluator and exact request/frontier bindings are source-composed. Signed evidence authenticates identity/context; it does not establish learning efficacy. Final checks now follow expensive registry preparation. |
| Daemon composition (`hepta-agentd`) | Explicit bootstrap, bounded lifetime queue, named producer, exact generation and final admission are implemented. Live trust/objective/owner updates still require explicit owner-generation reconstruction. |
| Application and recovery (`hepta-runtime`) | Separate FinalUse/migration owner applies the exact governed handoff and performs authorized recovery. Proposal or canary observation alone grants no runtime mutation authority. |
| Upstream self-iteration (`control.engineering`) | A real frozen-request coordinator remains uncomposed. Another forwarding facade would not supply independent iteration envelope/objective/grammar/budget/request binding. |
| Production qualification and longitudinal efficacy | Independent rollback/trust domains, actual target-host crash/recovery, telemetry, future-window efficacy, operator acceptance, activation and release remain unproved. All five readiness/acceptance/activation/release booleans remain false. |

The useful next product optimization is a genuinely frozen, independently
evaluated upstream request coordinator plus explicit generation refresh, followed
by deployment evidence. Those tasks require decisions/evidence from their
respective owners; this audit does not synthesize credentials, evaluation results
or deployment acceptance. A percentage completion score would conflate source,
composition, execution and external acceptance, so completion is assessed by
responsibility instead.

## Timing, storage and proof limits

The final gate is a local admission linearization point, not a distributed lease.
Local draining/fencing serializes with the retained mutex. Another process's Fleet
publication is not serialized by that mutex. Cancellation, expiry or publication
after admission may leave an already admitted synchronous transaction completing;
it requires durable reconciliation and cannot be rolled back by dropping a reply.
There is no claim of a hard latency deadline or fresh signature checks per byte.

The owner clock floor lasts only for this owner lifetime. Restart freshness still
depends on trusted host time and reconstruction from current independently
witnessed stores. Registries verify their open file description under the host's
exclusive/cooperative immutable-file contract; they do not attest arbitrary path
replacement or race an unrestricted concurrent external file mutator.

The external journal has at most 1,000,000 fixed 81-byte frames plus its 72-byte
header (81,000,072 bytes). It retains at most 32 MB of logical trusted digest
payload, plus vector capacity/overhead, and reads through a fixed 32 KiB buffer.
Its cached snapshot is not a live-history certificate. Dropping the handle loses
that retained digest witness: ordinary reopen checks checksums and replay grammar
but cannot independently identify a header-only or older complete valid prefix.
Recovery therefore needs independently retained fence/anchor history and an
attested rollback domain, rather than inferring prior acknowledgements from a
clean reopen. There is no atomic rollback across proposal and anchor files.

Full image verification deliberately costs O(history bytes), bounded by the
512 MiB parameter and 256 MiB topology physical file caps. Frame hashes use
32 KiB scratch space; history is not decoded or cloned for every append. Existing
capacity limits, repeated scans across adapter steps and holding the final lock
during postwrite confirmation must be measured on the selected host before
claiming the operational latency target. Two additional retained-file fault
fixtures corrupt the header inside the final callback, after preflight; the file
then grows from an actual append before postwrite verification rejects it and
retains poison. These deliberately violate the host's exclusive-file contract to
exercise the stage boundary. They do not inject a hardware sync failure or an
I/O read error.

## Validation evidence

| Check | Result and exact scope |
| --- | --- |
| Original workspace and Cargo.lock, scoped `just test`, Linux, `dev-small` profile | **294 passed, 1 originally ignored**: 78 plasticity, 82 intelligence, 119 learning-ledger and 15 runtime tests. Includes the two product adapter regressions, final-admission rejection/retry, all registry boundaries, postwrite image fault fixtures and actual live topology apply/fault/recovery. |
| Focused actual-source core `just test` | **78 passed, 0 skipped**; source symlinks and aggregate SHA256 were identical before/after (`004c042309f4bdd1b90ad054a34b62836b3f2c16c25f508c2be258a57ddf9a31`). This harness uses a generated dependency lock (`sha2` 0.10.9, `cfg-if` 1.0.5), not the repository's Cargo.lock. It supplements the original-workspace pass rather than replacing it. |
| Focused core `just fix` | Passed with the actual workspace Clippy lint configuration and `clippy.toml`; removed five redundant test-only clones. |
| Original-workspace scoped `just fix`, intelligence and plasticity | Passed with the original lockfile and `dev-small` profile. Existing deprecation, enum-size and test assertion warnings remain; this is not a workspace-wide strict-lint claim. |
| Actual-source isolated shared journal, `just test` | **12 passed, 0 skipped**: seven existing tests plus five new tests covering eighteen retained-file mutation/path combinations, healthy retry/rollover/reopen and the plain-reopen proof limit. Uses the actual journal/helper/tests and `hepta-types`, pinned official `tempfile` 3.27.0, with no substitute implementation; before/after source hashes matched. |
| CI deadline fixture | **45 passed** over five runs of nine tests; then the exact workflow's `python3 -m unittest discover -v -s scripts -p 'test_hepta_*.py'` command passed **685 tests, 0 skipped**. Production executor is unchanged. |
| Derived projections | Passed. |
| Detailed document/source verification | `PASS_HEPTA_DEVELOPMENT_DOCS_V8`: all 40 module source bindings verified; the 54 documented readiness gaps remain. The five affected navigation maps were migrated without changing claim boundaries. |
| Implementation-map adversarial checks | **130 passed** with `PYTHONPATH=scripts`, covering strict source identity, checkout/index isolation, alternate Git objects and evidence-path drift. |
| Repository formatting | `just fmt` completed; 45 unrelated baseline formatter changes were restored. |
| Full Agentd plus four related crates, original workspace | **Not executed**. The first build required explicit installed OpenSSL paths because `pkg-config` was absent. After resolving that discovery issue, dependency `rmcp`'s rustc received SIGKILL and the command exited 101 before any tests ran. Shared disk was also exhausted during this attempt; no specific cause of SIGKILL is asserted. Only that completed attempt's inactive generated target was removed. |
| Original-workspace scoped Agentd/intelligence/plasticity lint | Did not reach completion: dependency `zlib-rs` could not create its metadata directory because shared disk was full; exit 101. Only that completed attempt's inactive generated cache was removed. The subsequent two-crate lint pass above does not substitute for Agentd lint. |

The original ignored learning-ledger growth benchmark retains its target-host
qualification requirement. Agentd clock/final-admission, lifecycle and topology
writer-health regressions are mapped source tests, not claimed Agentd execution.
The prior audit's passes are historical evidence, not additional passes for this
changed candidate. This follow-up does not claim Windows or target-host execution.

## Convergence and remaining gates

This round closes the confirmed source and test defects. Final independent source
review covered guarded callback placement, unchanged retries, writer-state
propagation and the registry checker without finding a further confirmed defect.
This is convergence within the reviewed source boundary, not proof that every
future input, platform or storage fault is safe. The remaining gates are real upstream composition, exact
source/merge qualification, target-host performance/crash recovery, independent
security/semantic acceptance and learning efficacy. Source review alone cannot
close those gates or establish absence of every future defect.
