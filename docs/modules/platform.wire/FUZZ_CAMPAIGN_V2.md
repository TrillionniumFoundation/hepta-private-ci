# Three-scenario exact-source fuzz qualification

## Scope

The original `decode_frames` target remains intact. `managed_records` exercises the ordinary `ManagedAuthenticatedWireSession` owner through `into_record_stream`, including chunking, cooperative yields, mutation, reflection and replay. `policy_admission` tests a correctly re-digested denied producer, terminal managed-owner policy rejection and arbitrary record input. All keys and channel bindings are deterministic fixtures, not authenticated real peers.

The fuzz harness uses the existing public wire API. No checkpoint, store, authorization issuer, transport daemon or parallel owner is added. `MANAGED_RECORD_STREAM.md` defines the integration boundary and consuming cancellation/EOF contract. Authentication remains HMAC-SHA-256, not CRC and not encryption. Persistent effect recovery belongs to downstream owners; no speculative wire checkpoint is introduced.

## Toolchain and budget

The workflow pins `nightly-2026-09-20` and `cargo-fuzz 0.13.2`, replacing the observed cargo-fuzz 0.12.0/rustix 0.36.5 installation failure. Upstream reference: https://github.com/rust-fuzz/cargo-fuzz/releases/tag/0.13.2 . An installation change is not a claim that fuzzing ran: the installed versions, check/build logs and actual execution statistics are retained separately.

`duration_seconds` is now a total campaign execution budget, divided evenly across the three targets (integer division). Pull requests use 180 seconds total, scheduled runs 900, and manual runs accept 60..1800. Preparation is separate from that execution budget; each target also has a subprocess deadline. Target names and commands are fixed; manual input is passed through environment variables and validated as decimal digits, never interpolated into shell source.

The workflow remains read-only and checks out the exact PR head or dispatched commit. No candidate-source mutation or qualification-time formatting is allowed. The resolved standalone fuzz lock file is retained with its digest; this is not a claim that a generated lock was already committed to the repository.

## Evidence v2 and fail-closed behavior

`scripts/platform_wire_fuzz_campaign.py` creates `hepta.platform-wire.fuzz-campaign.v2` before toolchain preparation. It binds source SHA, tested SHA, source tree, workflow/ref, run/attempt, runner image, toolchain and command details. Each target records its status, elapsed time, exit code, executed-unit count and raw-log digest. Corpus and crash inventories retain file lengths and digests.

A command exit of zero is insufficient: positive libFuzzer final execution statistics must exist. Missing tools, failed preparation, interruption, source mismatch, absent or changed logs, and zero execution never pass. Failure in one executed target does not silently skip the other targets. Finalization preserves `not_run` and failure reasons before the enforcement step. No failed run manufactures target-host, reviewer, operations or release acceptance. This new v2 campaign receipt does not reinterpret the old single-target v1 receipt.

Eight Python unit tests cover bounded input, non-shell arguments, no-execution rejection, preparation failure, missing receipts, interruption, source/log mismatches and continued execution after a target failure. Mocked process tests validate the reporter only; they are not fuzz execution evidence.

## Remaining product and performance evidence

The Unix socket-pair regression uses real local OS I/O and the normal managed owner, but fixture authentication. Actual trusted exporter provisioning, independently authenticated peer admission and normal product-host integration still require transport-owner evidence. A bounded buffer or a passing socket fixture is not a target-host memory or latency measurement. Keep the protected target-host, independent semantic/security review, operations and release gates unchanged.

Run the current source and ordered-merge native checks, then this campaign on the final published commit. Preserve unrelated Lane A failures as separate blockers rather than attributing them all to fuzz installation.
