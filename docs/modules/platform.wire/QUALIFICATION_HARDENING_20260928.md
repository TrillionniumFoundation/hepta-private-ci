# platform.wire: command-bound qualification and managed-consumer properties

This follow-up extends PR #1094. Every execution result must bind the exact
containing source commit and tested tree; a parent commit, historical check
color, queued job, local author statement or generated fixture is not a
qualification receipt for a later revision.

Read this alongside `TECHNICAL.md`, `SECURITY_AND_QUALIFICATION.md`, and the
existing Lane A implementation map. It does not replace those documents,
create another canonical lifecycle status, or grant acceptance.

## Ownership and protocol boundaries retained

`ManagedRecordStream` still consumes the existing
`ManagedAuthenticatedWireSession`. No second authenticator, durable store,
replay journal, transport executor, product route, effect owner or test-only
authority path is introduced. The fixed HPTA/HPTM formats, authenticated
admission order, final-use authority, zeroizing retirement, accepted-prefix
delivery and cooperative work budgets are unchanged. A successful record does
not authorize its enclosed effect.

The stream owns no persistent checkpoint. A durable consumer must separately
prove that its checkpoint does not advance beyond its durable accepted and
committed prefix. Test-local counters below assert delivery order only; they do
not move checkpoint ownership into `platform.wire` or claim crash recovery for
an external consumer.

## Fuzz qualification changes

The campaign CLI and schema remain `init`, `seed`, `run`, `finalize`, `check`
and `hepta.platform-wire.fuzz-campaign.v2`. The three actual targets remain
`decode_frames`, `managed_records`, and `policy_admission`. Corpus,
crash-artifact, preparation-log and fuzz-lock inventories are retained. The
managed-record corpus has deterministic seeds for all seven mode branches,
including maximum-length/EOF admission and valid-prefix plus bad-MAC suffix
handling. The workflow verifies the exact seed bytes before harness
compilation, so a missing branch seed cannot silently inherit a historical
corpus.

The cargo-fuzz executable is installed with pinned stable `1.95.0` and pinned
`cargo-fuzz 0.13.2` into a runner-local isolated root. The root's `bin`
directory is exported through `GITHUB_PATH`. A separate later workflow step
requires `command -v cargo-fuzz` to resolve to that root and executes both
`cargo-fuzz --version` and `cargo +nightly-2026-09-20 fuzz --version`. This
checks the actual cross-step command context instead of proving availability
only inside the installation shell. Instrumented harness compilation and
execution continue to use pinned `nightly-2026-09-20` with LLVM tools.

Qualification checks the complete target command, corpus path, working
directory, target name, deterministic seed, sanitizer/runtime arguments,
per-target duration and process timeout. It also binds source/tested SHA,
source tree, workflow SHA/ref, run ID, attempt, event, compiler identities and
runner-image identity to the invocation. Positive retained execution
statistics, matching log digest and a strict integer zero exit code are
mandatory. JSON booleans or floats cannot masquerade as exit codes or counts.
Malformed objects, missing targets, stale attempts, changed budgets,
zero-execution logs and interrupted work fail closed.

The runner starts Cargo in an owned POSIX process group and retires that group
on timeout, interruption or wrapper exit, reaping the directly owned child.
Killing only Cargo can leave a libFuzzer descendant alive. This is process
lifecycle control for the selected Linux runner, not a sandbox guarantee
against a program that deliberately escapes its process group.

`run` invalidates earlier target successes before starting any child. A failing
target does not skip the remaining targets. `finalize` overwrites malformed
receipts with failed evidence and can be called again by `check`. It does not
reuse a prior successful result when the subject or invocation has changed.
Receipt consistency is not cryptographic proof of the artifact issuer; release
must still consume artifacts from the trusted workflow and require independent
review and operations acceptance.

## Generated properties through the public managed API

`tests/managed_stream_properties.rs` retains five public-owner properties:

| Property | Executed path and assertion |
|---|---|
| Partition and budget invariance | Deterministic uneven partition schedules across seven byte budgets, one-record work limit and eight authenticated frames; exact order and no duplication |
| EOF prefix preservation | Every nonempty truncated prefix of the second record preserves the first frame and fails consuming EOF |
| Authentication failure isolation | Multiple chunk sizes preserve only the authenticated first record; the bad suffix retires the owner, frees the record buffer and admits no replay |
| Cooperative multi-peer progress | A bounded round-robin fixture lets a small peer complete while a large peer remains partial; cancellation retires the latter |
| Fresh-session boundary | Partial input is discarded on retirement; the old session's record cannot enter a fresh channel-bound session |

`tests/managed_consumer_contracts.rs` adds five consumer-facing contracts on the
same public path:

| Consumer contract | Executed path and assertion |
|---|---|
| Yield-aware continuation | The consumer retains the unconsumed suffix, continues after every bounded yield and receives the same ordered frame sequence across chunk and byte-budget combinations |
| Prefix-before-terminal ordering | A valid authenticated prefix is delivered exactly once before a tampered suffix becomes terminal; the test-local committed prefix cannot advance again after retirement |
| Authentication before dispatch | A tampered first record produces no admitted frame and therefore never calls the consumer callback |
| Rotation and restart isolation | Rotation requires a fresh session identity; the newly rotated peers communicate, while an old record poisons a fresh replay probe and cannot be retried in place |
| Bounded peer scheduling and release | Eight differently sized peers make round-robin progress under a 64-byte feed budget; aggregate retained capacity stays within an allocator-tolerant admitted-byte bound and becomes zero after retirement |

These tests call `into_record_stream`, `feed`, `seal_envelope`, `finish`,
`rotate` and `retire` on the public owner. They are not an alternate product
protocol. Their generated schedules are deterministic rather than an
exhaustive formal proof. Bindings, keys and the round-robin driver are explicit
fixtures; this is not real authenticated transport, target-host or independent
acceptance evidence.

## Managed runtime.codex composition

The runtime.codex adapter regressions compose existing public owners rather
than introducing a test-only decoder or second authority path. A V3 product
intent is encoded by the canonical adapter, sealed by the existing
`ManagedAuthenticatedWireSession`, incrementally admitted by
`ManagedRecordStream`, then decoded and adapted by the normal runtime.codex
functions. The composition covers uneven fragmentation and cooperative byte
budgets while preserving the request digest and the existing authority-free,
indeterminate adapter result.

A second regression presents one valid record followed by a MAC-tampered
record. The authenticated prefix is adapted exactly once before the terminal
suffix is acted on; the connection owner is retired, its record buffer is
released and replay cannot advance the test-local committed-prefix counter. A
third regression verifies that a tampered first record produces no admitted
frame and therefore never reaches the adapter. These counters are assertions
on prefix ordering, not durable checkpoint implementations or recovery
receipts. The keys and channel binding remain fixtures and do not claim network
peer identity, exporter provisioning or product activation.

## Measurement before optimization

The existing `managed_stream_resources` regressions and release-mode
`managed_record_profile` remain mandatory. The single-session profile records
peak record-buffer capacity, capacity and byte length retained after the
workload, bounded yields, delivery counts and seal/decode percentiles across
nine payload/chunk scenarios. Its validator requires exact scenario coverage,
no lost or duplicated frames, an empty post-workload byte length and retained
capacity no greater than the observed peak. It deliberately does not invent a
shrink threshold: retained capacity is evidence for a later allocation/reuse
decision, not permission to change buffering semantics without target-host
measurements.

`managed_fleet_profile` adds release-mode multi-peer measurement through the
same public owner path. It executes six scenarios: 4, 16 and 32 peers at base
payloads of 64 and 4096 bytes, with a 17-byte per-peer payload stride. Every
sample creates fresh session identity and key fixtures, feeds peers in bounded
round-robin order and records:

- exact delivered frame count, feed calls and cooperative yields;
- aggregate buffered-byte and retained-capacity peaks;
- capacity and buffered length after the workload;
- aggregate capacity after explicit retirement;
- scheduler turns to first and last completion and their observed gap;
- release-mode round p50, p95 and p99 elapsed time.

The validator requires six unique scenarios, the exact workload and budgets,
one delivery per peer per round, ordered timing percentiles, consistent
fairness accounting, zero retained buffered bytes after workload and zero
record-buffer capacity after retirement. Capacity is bounded against twice the
admitted wire bytes so allocator granularity is tolerated without allowing
speculative allocation from an announced body length.

The core source-head/base-merge workflow and the exact source/synthetic-merge
workflow run the public consumer contracts and a small release fleet profile.
The dedicated throughput workflow runs release HPTA throughput and fleet
measurements together and binds both JSON reports into
`hepta.platform-wire.throughput-receipt.v2`. Cloud-runner values remain
measurement-only; no hard performance threshold or host-equivalence claim is
created.

The protected target-host workflow additionally runs the existing
single-session profile for nine scenarios with 512 iterations and the fleet
profile for six scenarios with 64 rounds. GNU `time -v` separately records the
maximum resident-set observation for each process. Both JSON reports and both
resource reports are SHA-256-bound into the exact-source target-host receipt.
This measures release in-process managed HPTM work on the selected host. It
does not measure authenticated network ingress, allocator-call counts,
transport queue wait, multi-process pressure or deployment acceptance, and the
receipt states those nonclaims explicitly.

Record-buffer capacity is not whole-process memory, a release process RSS is
not an allocator trace, and fixture round-robin progress is not proof of a
production executor's scheduling policy. Use the protected host evidence
before making buffering, zero-copy, batching or scheduling changes.

## Reproduction and evidence scope

Run the campaign regressions with:

```sh
python3 -m unittest discover -s scripts/tests -p test_platform_wire_fuzz_campaign.py -v
```

Run the managed properties, consumer contracts, adapter composition and current
core targets with:

```sh
cargo test --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-wire --test managed_stream_properties
cargo test --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-wire --test managed_consumer_contracts
cargo test --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-codex-adapter --lib wire::tests
cargo test --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-wire --all-targets
cargo clippy --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-wire -p codex-hepta-codex-adapter --all-targets --no-deps -- -D warnings
python3 scripts/platform_wire_managed_profile.py --self-test
python3 scripts/platform_wire_managed_fleet_profile.py --self-test
cargo run --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-wire --release --example managed_fleet_profile -- 8
```

Historical authoring notes on parent revisions are not substituted for current
execution. Native Rust tests, strict Clippy, all three real fuzz campaigns,
release measurements, exact source and ordered synthetic merge must be
reported by the read-only workflows on the final published source.

The current minimum floors are 102 all-target wire tests, five explicit
managed-consumer contract tests, six explicit managed-resource tests, nine
single-session profile-validator tests, nine fleet-profile validator tests and
12 filtered context/runtime adapter tests. A later accidental filter, missing
binary or stale suite cannot reuse an older smaller success threshold. Do not
convert absent, queued, cancelled, startup-failed or historical runs into a
passed current-source receipt. Broad repository or Lane A failures must be
diagnosed independently rather than attributed to cargo-fuzz or platform.wire
without their own logs.

## Remaining external acceptance gates

Actual transport identity and fresh exporter/key provisioning, real network
ingress and consumer composition, cancellation and deadlines under the
production executor, restart/recovery, mixed-version and rolling-upgrade
behavior, allocator and transport-queue behavior under production pressure,
and any consumer-owned durable checkpoint still require
source/artifact-bound evidence from their existing owners. The protected
single-session and fleet profiles narrow the resource gap but do not close
those transport, scheduling, recovery or deployment gates.

Only existing transport, resource, checkpoint and effect owners may close
those gates. Independent semantic/security review, operations acceptance and
release remain separate receipts. This change does not assert production
activation, release or independent acceptance, and does not change lifecycle
booleans to manufacture completion.
