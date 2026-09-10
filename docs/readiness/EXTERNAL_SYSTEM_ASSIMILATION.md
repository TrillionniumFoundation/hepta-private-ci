# Authorized external-system assimilation specification

**Overlay:** `HEPTA-V8-PRECODING-READINESS` v8.2.0-readiness
**Initial target:** an explicitly authorized, unprivileged Debian service in an isolated host or rootfs
**Claim posture:** no autonomous propagation, takeover or production mutation

## 1. Scope, consent and non-propagation boundary

Assimilation means converting an authorized external system into a typed, observable and rollback-capable Hepta organ. It does not mean self-spreading, privilege escalation, persistence outside consent or automatic takeover. Every host, service, filesystem root, network destination and operation must be explicitly enrolled through `CapabilityBoundaryV1`.

Unknown scope, absent authorization, root credential exposure or an attempt to enroll another host without a new principal grant stops the process. The first implementation is read-only discovery and sandboxed behavior parity.

## 2. Component ownership map

The capability is decomposed without introducing a second central owner:

| Component | Existing owners | Responsibility |
|---|---|---|
| `assimilation.discovery` | `control.engineering`, `runtime.supervisor` | bounded inventory |
| `assimilation.manifest` | `platform.types` | canonical system records |
| `assimilation.contract-synthesis` | `platform.wire`, `control.engineering` | typed adapter candidates |
| `bridge.debian` | `runtime.agentd`, `kernel.authority`, `kernel.operations` | effect boundary |
| `assimilation.sandbox` | `control.engineering`, `runtime.supervisor` | isolated execution |
| `assimilation.state-migration` | `kernel.operations`, `runtime.agentd` | quiesce, migrate, reconcile |
| `assimilation.provenance` | `kernel.evidence` | SBOM and source evidence |
| `assimilation.qualifier` | `learning.eval`, `kernel.evidence` | independent decisions |
| `organ.federation` | `runtime.fleet`, `memory.federation` | enrolled multi-host coordination |

Cross-owner mutation uses durable intent, outbox, destination dedupe, acknowledgement and fenced reconciliation.

## 3. Discovery and external-system manifest

Discovery is scoped, read-only and reproducible. For Debian it records:

```text
/etc/os-release and kernel/architecture identity
dpkg package/status and APT source/keyring digests
systemd unit files, drop-ins, enablement and dependency graph
D-Bus names/interfaces, sockets and activation policy
process, cgroup, namespace, mount and device topology
users, groups, capabilities and service credentials by reference only
listening sockets, firewall-visible destinations and DNS policy
configuration roots, mutable state roots, logs and backup ownership
resource, restart, health and failure behavior
```

Raw secrets are never copied into the manifest. `ExternalSystemManifestV1` contains digests and bounded references. `ServiceGraphV1` represents dependencies, sockets, D-Bus, state ownership and canonical topological order. Cycles are explicit and require a start/stop strategy.

## 4. Contract synthesis and capability boundary

Contract synthesis derives candidates from declared APIs, CLI help, D-Bus introspection, systemd metadata and observed traces. Generated operations have typed inputs, outputs, preconditions, side effects, idempotency, terminal observation, timeouts and error mapping. Inferred contracts remain candidates until reviewed and tested.

`CapabilityBoundaryV1` lists allowed and denied operations, filesystem roots, service units, destinations, resource ceiling, expiry and revocation. An adapter cannot mint the boundary it consumes. Synthesis cannot convert documentation text or model output into authority.

## 5. Debian and POSIX adapter semantics

The Debian bridge separates read operations from effects:

- package inventory and version query are read-only;
- package download, install, remove and configure are separate effect classes;
- APT source/key changes require a stronger explicit grant;
- systemd start, stop, reload, enable and mask are distinct operations;
- D-Bus calls bind destination, interface, method, signature and final payload;
- filesystem writes bind canonical path, mount generation and content digest;
- cgroup and namespace changes bind process generation and resource policy.

Shell text is not a protocol. Commands are assembled from typed arguments with no implicit interpolation. Root-level operations are excluded from initial slices. Package maintainer scripts are treated as untrusted effects and run only in the sandbox until separately qualified.

## 6. Sandbox, migration and rollback

Candidates execute in an isolated VM, container or disposable rootfs with no production secrets, bounded egress and exact base image. Behavior parity compares service API, state transitions, logs, resource use, failure modes and restart semantics.

`MigrationPlanV1` defines quiescence, ordered steps, state ownership, verification, compensation, downtime bound and rollback. `RollbackPointV1` binds package, configuration, service and data snapshots plus restore validation. A migration never assumes that reinstalling a package restores external state.

Crash, storage-full, partial package configuration, service timeout, acknowledgement loss and host reboot are mandatory fault points. Unknown external effect remains indeterminate and blocks further mutation until reconciled.

## 7. Provenance, qualification and federation

Provenance binds source package, repository, signature/keyring, SBOM, license, vulnerability report, build recipe, binary digest, adapter source, sandbox image and evaluator. A vulnerability waiver is scoped and expiring; it is not silently inherited by future versions.

`AssimilationQualificationReceiptV1` covers behavior parity, security, resources, faults and rollback with an evaluator distinct from the generator and production operator. Federation enrolls hosts explicitly, uses short-lived leases and bounded remote reads, and isolates failures. A host cannot enroll peers or copy credentials autonomously.

## 8. Lifecycle and maturity ladder

```text
A0 discovered: read-only manifest and graph
A1 wrapped: one unprivileged service exposed as a dormant organ
A2 controlled: bounded start/stop/query/config operations under explicit grants
A3 adaptive sandbox: candidate improvements generated and evaluated only in isolation
A4 shadow/canary: qualified candidate on a bounded enrolled host
A5 federated: multiple explicitly enrolled hosts with failure isolation
```

Each level requires predecessor evidence. “Debian assimilated” is never a single boolean; claims name exact host, service, boundary, adapter and lifecycle generation.

## 9. Failure taxonomy and security

Hard failures include absent consent, scope mismatch, inventory drift, unsigned or unexpected package, unresolved vulnerability, secret exposure, contract ambiguity, path escape, maintainer-script effect, service graph cycle without strategy, state-owner conflict, rollback failure, evaluator collision and propagation attempt.

The response is reject, quarantine, restore predecessor or request human action. The system never widens privileges to finish a migration. Untrusted repository and package metadata remain evidence.

## 10. Performance envelope

Discovery has bounded files, packages, units, sockets and encoded bytes with explicit truncation-before-analysis policy. Adapter calls have per-operation deadline, output bound, process count and resource ceiling. Sandbox runs have CPU, memory, disk, network and wall-clock budgets. Federation has bounded peers, lease TTL and reconciliation backlog.

Reports include discovery duration, manifest size, graph nodes/edges, adapter latency, restart time, storage delta, CPU/memory, network, fault recovery and rollback duration.

## 11. Golden fixtures and tests

Fixtures include a minimal unprivileged Debian service, dependency cycle, stale package inventory, altered APT source, malicious maintainer script, D-Bus signature mismatch, symlink escape, hidden secret file, partial migration, reboot during configuration, acknowledgement loss, rollback restore, evaluator identity collision and unauthorized peer enrollment.

The first end-to-end fixture must discover, wrap, observe, stop/start, inject a fault and restore one service without root, unrestricted network or production data. Any propagation or privilege expansion attempt is a mandatory rejection.

## 12. Implementation sequence

Implement canonical manifests and graphs, read-only Debian discovery, capability boundary, typed service query adapter, sandbox behavior parity, provenance, rollback snapshot, unprivileged start/stop, configuration candidate, fault qualification, dormant organ registration, shadow/canary and federation last.

## 13. Coding-entry checklist

Coding may start when all seven assimilation protocols plus sandbox receipt compile, the nine components are mapped to existing owners and target roots, an explicitly authorized unprivileged fixture exists, root/network/secret denial is tested, state ownership and rollback are defined, and no autonomous propagation or production activation claim is made.

## Appendix A. Closed gap and protocol mapping

This appendix records repository specification closure only. It does not grant runtime, model, provider, external-effect, operator, promotion or release authority.

### Protocol bindings

- `ExternalSystemManifestV1`
- `ServiceGraphV1`
- `CapabilityBoundaryV1`
- `AssimilationProposalV1`
- `MigrationPlanV1`
- `AssimilationQualificationReceiptV1`
- `RollbackPointV1`
- `SandboxExecutionReceiptV1`

### Closed specification gaps

- `RDY-GAP-ASM-001`
- `RDY-GAP-ASM-002`
- `RDY-GAP-ASM-003`
- `RDY-GAP-ASM-004`
- `RDY-GAP-ASM-005`
- `RDY-GAP-ASM-006`
- `RDY-GAP-ASM-007`
- `RDY-GAP-ASM-008`
- `RDY-GAP-ASM-009`
