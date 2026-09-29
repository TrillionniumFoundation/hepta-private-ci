# platform.wire module evidence map

This file is the navigation entry for the current `platform.wire` implementation and its evidence gates. It does not replace the protocol specifications or grant deployment authority.

## Canonical reading order

1. [`CURRENT_IMPLEMENTATION.md`](../../lane-a-foundation/platform.wire/CURRENT_IMPLEMENTATION.md) describes the current executable/source contract and named product callers.
2. [`TECHNICAL.md`](TECHNICAL.md) records the broader architecture, ownership, compatibility and work-package design.
3. [`SECURITY_AND_QUALIFICATION.md`](SECURITY_AND_QUALIFICATION.md) defines session security, key and channel-binding responsibilities, qualification receipts and nonclaims.
4. [`PERFORMANCE_INTAKE_20260929.md`](PERFORMANCE_INTAKE_20260929.md) defines the registered five-path comparison with the gRPC reference. Every path must satisfy package-size ratio `<= 0.70` and p99 ratio `<= 0.80`.
5. [`PRODUCTION_INTAKE_20260929.md`](PRODUCTION_INTAKE_20260929.md) defines the registered eight-scenario production-composition observation: authenticated non-loopback ingress, gateway/provider E2E, bounded pressure, deadline/cancellation, reconnect/restart, key rotation/retirement, mixed-version rolling and canary rollback.
6. [`STATUS.md`](STATUS.md) is generated from source-bound receipts by `scripts/platform_wire_status.py` and is the lifecycle truth. Do not edit its booleans by hand.

Dated remediation and resource documents preserve implementation rationale and historical source identities. They do not override the current source candidate, the generated lifecycle state or exact-source workflow receipts.

## Lifecycle contract

| State | Required facts |
|---|---|
| `Designed` | required design documents, including this evidence map |
| `Implemented` | the required native `codex-rs/hepta-wire` source surfaces |
| `Qualified` | same-source exact-head, deterministic synthetic-merge and protected target-host receipts |
| `Accepted` | `Qualified` plus a passed same-source five-path performance receipt, a passed same-source eight-scenario production-composition receipt, and distinct independent reviewer and operations receipts |
| `Released` | `Accepted` plus a source-bound release receipt and artifact digest |

Source code, ordinary pull-request CI, local fixtures and in-process profiles cannot self-issue production observation, reviewer acceptance, operations acceptance or release. Missing, stale, malformed, failing or source-inconsistent evidence fails closed.

## Evidence producers and workflows

- `.github/workflows/platform-wire-core.yml` runs the actual crate, resource/consumer contracts, strict Clippy and release profiles on source-head and ordered merge.
- `.github/workflows/platform-wire-exact-qualification.yml` produces exact-source and deterministic synthetic-merge qualification evidence.
- `.github/workflows/platform-wire-target-host.yml` is the protected selected-host qualification path.
- `.github/workflows/platform-wire-performance-intake.yml` admits only a registered exact-source five-path measurement artifact.
- `.github/workflows/platform-wire-production-contract.yml` validates the closed production evidence contracts on source-head and ordered merge; it does not claim a deployment occurred.
- `.github/workflows/platform-wire-production-intake.yml` admits only a registered exact-source deployment-observation artifact in the protected `platform-wire-production` environment.

`PERFORMANCE_PRODUCERS.json` and `PRODUCTION_PRODUCERS.json` are closed registries. Dispatch inputs select an enabled, reviewed registration; they cannot create or widen one. An empty registry intentionally means that no external producer is currently accepted.

## Developer checks

```bash
python3 scripts/platform_wire_performance_gate.py --self-test
python3 scripts/platform_wire_production_gate.py --self-test
python3 scripts/platform_wire_status.py self-test
python3 scripts/platform_wire_status.py check-doc
cargo test --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-wire --all-targets
cargo clippy --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-wire --all-targets --no-deps -- -D warnings
```

These commands validate source and evidence contracts. They do not substitute for authenticated real-network observations, selected-host execution, paired gRPC measurements, independent decisions, canary/promotion or release.
