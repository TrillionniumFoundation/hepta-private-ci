# Managed HPTM resource admission and measurement — 2026-09-28

Read with [TECHNICAL.md](TECHNICAL.md), [SECURITY_AND_QUALIFICATION.md](SECURITY_AND_QUALIFICATION.md) and [STATUS.md](STATUS.md). This is an implementation/validation supplement, not a competing lifecycle status registry.

## Source and boundary

This revision extends PR #1094 on `codex/platform-wire-final-convergence-20260925`, retaining the existing `ManagedAuthenticatedWireSession` and its consuming `into_record_stream` adapter. It adds no transport, memory-store dependency, business authority, durable checkpoint or alternative replay owner. Frozen HPTA V1/V2 bytes, HPTN negotiation and HPTM V1 MAC/sequence interpretation are unchanged. Authentication and final-use authorization remain distinct.

Earlier review prose describing a CRC-based wire protocol, `ManagedWireSession`, persistent wire checkpoints or proven physical adapters does not describe this source. HPTA V1/V2 use unkeyed SHA-256 integrity digests; HPTM adds directional HMAC-SHA-256. A source fixture channel binding is not a TLS exporter or independently authenticated ingress.

## Resource defect and correction

The prior stream reserved `target - pending.len()` after a fixed prefix announced a full record. A peer could therefore cause reservation of the permitted maximum record body while supplying only one body byte. The allocation was individually capped but multiplied across slow partial peers.

`ManagedRecordStream::reserve_admitted` now reserves only in response to bytes actually admitted by the per-feed budget. Geometric growth avoids a reallocation per one-byte fragment. Growth is bounded by the current admitted record ceiling; no body is reserved merely because its length was declared. A known-wrong session identifier is rejected at the fixed 50-byte prefix before body admission. Matching that identifier is not authentication: the existing owner still verifies the complete MAC, directional sequence and frozen schema policy before publishing a frame.

The same owner is retired after terminal framing or authentication error. Already admitted prefix frames remain in the returned batch, exactly once. Retirement drops the record buffer and key-bearing owner state; there is no reset/replay shortcut. Empty feeds do not allocate, yield or advance a partial record.

`buffer_capacity_bytes()` reports retained `Vec` record-buffer capacity, not process RSS, allocator metadata, transport buffers, returned frame storage or other peers. An active session can retain capacity previously needed for a complete legitimate record until retirement. Per-host connection counts, deadlines and total resource policy remain the transport owner's responsibility.

## Executable regression mapping

`tests/managed_stream_resources.rs` contains six public-API regressions:

| Regression | Required observation |
|---|---|
| Maximum announcement with one body byte | No speculative maximum-body allocation; consuming EOF rejects the partial record |
| Wrong session prefix | Consume only the fixed prefix; reject without frame publication; retire both directions |
| Valid frame plus wrong-session suffix | Deliver the valid prefix once, then terminate |
| One-byte fragmentation | Preserve the authenticated frame with bounded geometric capacity growth |
| 32 slow partial peers | Sum of retained record-buffer capacities follows received prefixes, not declared bodies |
| Empty feeds | No allocation, false yield, duplicated frame or progress |

The existing `managed_records` libFuzzer target is extended from five to seven modes: valid fragmentation, tamper, replay, wrong binding, reflection, speculative-body announcement and next-sequence MAC corruption after a valid prefix. Every mode uses the existing managed owner with byte/record budgets. The target checks terminal retirement, prefix preservation and progress; it does not bypass authentication with a mock decoder.

The positive-path `managed_fixture` maps empty corpus data to a one-byte legal payload. It does not widen the frozen nonempty-payload contract or suppress constructor errors. Raw invalid records are still passed unchanged to the receive boundary. `tests/fuzz_fixture_smoke.rs` imports that actual fixture and verifies empty/short corpus operation, authenticated exchange, producer denial and direct rejection of an empty HPTA V2 envelope. This catches fixture construction failures in ordinary native CI before an expensive fuzz campaign.

## Measured managed-path profile

`examples/managed_record_profile.rs` executes nine release-build scenarios: payload sizes 1, 64 and 4096 bytes crossed with transport fragments of 1, 37 and 512 bytes. One byte is the protocol's legal minimum; zero-byte envelopes remain rejected. Each scenario processes 256 records in qualification, using a 37-byte and one-record per-feed budget. It records:

- seal and decode-plus-delivery p50/p95/p99 nanoseconds;
- exact delivered frame counts, wire bytes, feed calls and budget yields;
- observed record-buffer capacity growth and peaks;
- returned payload bytes per frame.

Decode-plus-delivery includes the measurement consumer's frame comparison and explicit thread yield; it is not a measurement of an async production scheduler. Capacity-growth events are not allocator-call counts. The profile does not measure queue waiting, full-process RSS, secret-copy destruction, real TLS ingress or independent acceptance. Those nonclaims are machine-readable and must remain false.

`scripts/platform_wire_managed_profile.py` validates complete scenario coverage, exact counts, release mode, timing shape, bounded buffer accounting and required yields. Its eight Python self-tests use synthetic validator fixtures; those values are never published as performance measurements. Boolean values cannot substitute for numeric payload or budget fields. The validator enforces measurement completeness and invariants, not a host-independent latency SLO or a proven speedup against a historical baseline.

## Qualification commands and evidence

The existing read-only `platform-wire-core.yml` executes both source-head and deterministic ordered base-merge lanes. It retains all existing checks, requires at least 91 wire tests and eight isolated HTTP parser tests, and adds explicit six-test resource regression selection, eight validator self-tests, release example build/run and measurement validation. The new fuzz fixture smoke regression is included by `--all-targets`. Raw measurements and command logs are hashed into the same source/tree/tested-tree-bound artifact. A failed command fails the job; measurements do not produce acceptance or release receipts.

Manual dispatch now requires an immutable distinct `base_sha`; it no longer silently tests a source against itself as the integration base. PR runs continue to use the PR's fixed head/base tuple.

For local execution from the repository root:

```sh
cargo test --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-wire --all-targets
cargo clippy --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-wire --all-targets --no-deps -- -D warnings
python3 scripts/platform_wire_managed_profile.py --self-test
cargo run --release --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-wire --example managed_record_profile -- 256 > /tmp/managed-wire-profile.json
python3 scripts/platform_wire_managed_profile.py --input /tmp/managed-wire-profile.json --iterations 256
```

At publication, source existence is not a final execution result. Predecessor `8fd0884b360269495fd6d9361e7237a1a6bfd2c0` source-head artifact from run `36415738779` reported 91 native tests passed and a strict Clippy failure on a redundant method closure; that closure was fixed without disabling the lint. The next candidate `0aa386c8a30eaacbd910acc19bc62b920e838d72`, run `36417599924`, base-merge artifact `10967427736`, passed native tests and strict Clippy but rejected the initial zero-byte measurement payload. This revision corrects the measurement/fixture setup while retaining protocol rejection. Neither predecessor result is inherited as a passing result of this revision. The final SHA requires its own run and artifacts.

## Remaining independent product evidence

Keep `Qualified`, `Accepted` and `Released` evidence-derived. Actual authenticated peer admission/exporter provisioning, real product adapters, target-host restart/rotation/mixed-version behavior, full-host resource measurements and distinct reviewer/operations acceptance require their own valid receipts. This source/CI change does not self-attest them or introduce a second owner to simulate their completion.
