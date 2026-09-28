# runtime.supervisor production-closure candidate

**Candidate branch:** `codex/runtime-supervisor-production-closure-20260928`

**Source base:** `9dc892603d57a2c2fb064d6568e7aaee253aa9c3`

This overlay is an implementation and verification map. It does not claim
activation, operator acceptance, promotion or release.

## Implemented source boundaries

- Stop and Kill persist an exact-target intent before restart cancellation,
  lifecycle mutation or signaling. Kill may supersede Stop only for the same
  process identity. The original stop deadline survives daemon restart.
- restart claims bind predecessor and replacement process identities; stale
  owners cannot complete another generation.
- `ControlFailureDisposition` preserves `not_started`,
  `target_identity_stale`, `already_completed`,
  `persistence_indeterminate` and `recovery_required` through the daemon RPC.
- `ControlDiagnosticsSnapshot` reports progress, blocker, target generation,
  persistence/recovery state and actual resource-enforcement capability without
  command arguments, environment values or filesystem paths.
- `ControlLatencySnapshot` exposes bounded log2 p50/p95/p99 evidence for full
  admitted operations and the target-validation, intent-persistence,
  effect-dispatch, exit-observation, metadata-commit and audit-publication
  stages. A zero sample count is explicit and is not interpreted as zero cost.

## Exact-candidate verification

`.github/workflows/runtime-supervisor-production-closure.yml` executes formatting,
default/all-feature checks, package tests, strict Clippy, focused crash/fencing
fixtures, Linux pidfd/process-host probes, a macOS build/test lane and document
truth checks against the same commit SHA. Every lane preserves logs as an
artifact and the final gate fails unless all required outcomes succeed.

## Resource truth

The native operation timeout is enforced. Memory, subprocess-count and network
limits remain `declared_only` until a selected host installs and proves a kernel
mechanism. Configuration acceptance must not be reported as enforcement.

## Still-open external boundaries

- durable Drain and complete launch-before-lease recovery;
- selected-host 256-process mixed-load and soak receipts;
- production key provision, writer isolation and independent operator/security
  acceptance;
- deployment-specific memory, process-tree and network containment evidence.
