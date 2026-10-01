# platform.wire module evidence map

This file is the navigation entry for the current `platform.wire` implementation and its evidence gates. It does not replace the protocol specifications or grant deployment authority.

## Canonical reading order

1. [`CURRENT_IMPLEMENTATION.md`](../../lane-a-foundation/platform.wire/CURRENT_IMPLEMENTATION.md) describes the current executable/source contract and named product callers.
2. [`HARDENED_SESSION.md`](HARDENED_SESSION.md) defines the unique production owner, typed bound record stream, terminal key destruction, feature boundary, rotation and compile-fail API contract.
3. [`TECHNICAL.md`](TECHNICAL.md) records the broader architecture, ownership, compatibility and work-package design.
4. [`SECURITY_AND_QUALIFICATION.md`](SECURITY_AND_QUALIFICATION.md) defines session security, key and channel-binding responsibilities, qualification receipts and nonclaims.
5. [`PERFORMANCE_INTAKE_20260929.md`](PERFORMANCE_INTAKE_20260929.md) defines the registered five-path comparison with the gRPC reference. Every path must satisfy package-size ratio `<= 0.70` and p99 ratio `<= 0.80`.
6. [`PRODUCTION_INTAKE_20260929.md`](PRODUCTION_INTAKE_20260929.md) defines the registered eight-scenario production-composition observation: authenticated non-loopback ingress, gateway/provider E2E, bounded pressure, deadline/cancellation, reconnect/restart, key rotation/retirement, mixed-version rolling and canary rollback.
7. [`STATUS.md`](STATUS.md) is generated from source-bound receipts by `scripts/platform_wire_status.py`. Do not edit its booleans by hand. The evaluator checks receipt consistency; the importing owner must authenticate workflow provenance and approver identities before supplying receipts.

Dated remediation and resource documents preserve implementation rationale and historical source identities. They do not override the current source candidate, the generated lifecycle state or exact-source workflow receipts.

## Lifecycle contract

| State | Required facts |
|---|---|
| `Designed` | required design documents, including this evidence map |
| `Implemented` | the required native `codex-rs/hepta-wire` source surfaces |
| `Qualified` | same-source exact-head, deterministic synthetic-merge, protected target-host and passed three-target libFuzzer campaign receipts |
| `Accepted` | `Qualified` plus a passed same-source five-path performance receipt, a passed same-source eight-scenario production-composition receipt, and distinct independent reviewer and operations receipts |
| `Released` | `Accepted` plus a source-bound release receipt and artifact digest |

Source code, ordinary pull-request CI, local fixtures and in-process profiles cannot self-issue production observation, reviewer acceptance, operations acceptance or release. Missing, stale, malformed, failing or source-inconsistent evidence fails closed.

The offline evaluator does not authenticate a GitHub run, protected environment,
artifact origin or human identity. Well-formed local JSON is insufficient to
establish those facts. Its output is a consistency report over trusted imported
evidence, and cannot itself authorize deployment or release.

## Production API contract

Production integrations disable default features and enable only `production`. Their only authenticated owner chain is:

```text
HardenedManagedWireSession
    -> HardenedRecordStream<C: BoundPayloadCodec>
    -> C::Value
```

The raw `WireSession`, authenticated owner, managed owner and raw-envelope record stream are compatibility surfaces for tests, fuzzing, qualification and migration. They are absent from the production-only public API. Any terminal authentication, admission, binding, typed-decode or canonicalization error immediately drops the unique key-bearing child owner. Only immutable `WireSessionMetadata` remains observable.

`HardenedRecordStreamBudget` charges accepted source bytes, complete record
attempts and serialized frame work. A cooperative yield reports exact consumed
bytes; the consumer retains the unconsumed suffix and delivers any valid typed
prefix once. Terminal failure and partial-record EOF destroy session keys and
require a fresh connection. See [`HARDENED_SESSION.md`](HARDENED_SESSION.md) for
the error, budget, canonicalization and rotation contracts.

Current product callers still use the default `protocol-tooling` feature:
runtime status is a read-only HPTA V2 response, context receipts are compatibility
DTOs, and the runtime.codex V3 path performs an in-process frame/codec round trip
before final-use claim. They do not construct the hardened authenticated
transport owner. Production transport composition, peer/channel/key provenance
and migration of these callers remain incomplete.

## Evidence producers and workflows

- `.github/workflows/platform-wire-core.yml` runs the actual crate, resource/consumer contracts, strict Clippy and release profiles on source-head and ordered merge.
- `.github/workflows/platform-wire-production-surface.yml` compiles the positive production-only surface and requires lower-level escape fixtures to fail.
- `.github/workflows/platform-wire-exact.yml` produces exact-source and deterministic synthetic-merge qualification evidence.
- `.github/workflows/platform-wire-fuzz.yml` executes and retains exact-source `decode_frames`, `managed_records` and `policy_admission` campaigns; all three are required for qualification.
- `.github/workflows/platform-wire-target-host.yml` is the protected selected-host qualification path.
- `.github/workflows/platform-wire-performance-intake.yml` admits only a registered exact-source five-path measurement artifact.
- `.github/workflows/platform-wire-production-contract.yml` validates the closed production evidence contracts on source-head and ordered merge; it does not claim a deployment occurred.
- `.github/workflows/platform-wire-production-intake.yml` admits only a registered exact-source deployment-observation artifact in the protected `platform-wire-production` environment.
- `.github/workflows/actionlint.yml` statically validates every workflow's syntax, expressions and context availability.

`PERFORMANCE_PRODUCERS.json` and `PRODUCTION_PRODUCERS.json` are closed registries. Dispatch inputs select an enabled, reviewed registration; they cannot create or widen one. An empty registry intentionally means that no external producer is currently accepted.

## Developer checks

```bash
python3 scripts/platform_wire_performance_gate.py --self-test
python3 scripts/platform_wire_production_gate.py --self-test
python3 scripts/platform_wire_production_surface.py self-test
python3 scripts/platform_wire_production_surface.py verify
python3 scripts/platform_wire_status.py self-test
python3 scripts/platform_wire_status.py check-doc
just test --locked -p codex-hepta-wire --all-targets
cargo check --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-wire --no-default-features --features production
cargo clippy --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-wire --all-targets --no-deps -- -D warnings
```

These commands validate source and evidence contracts. They do not substitute for authenticated real-network observations, selected-host execution, paired gRPC measurements, independent decisions, canary/promotion or release.
