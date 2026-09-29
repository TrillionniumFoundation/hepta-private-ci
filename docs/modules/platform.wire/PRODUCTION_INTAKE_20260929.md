# platform.wire protected production-composition intake

Date: 2026-09-29. This document defines a repository-controlled evidence intake. It does not manufacture a deployment, authenticate an unregistered observation producer, approve a rollout, activate a product path or release an artifact.

## Why this gate exists

The exact-source, ordered-merge and protected-target workflows prove source, integration and selected-host command execution. Release-built profiles measure in-process throughput, fairness, staging retention and process resources. The five-path gate separately compares package size and p99 latency with the registered gRPC reference. None of those facts, by itself, proves that a deployed product used authenticated non-loopback ingress, bounded the complete gateway/provider path, recovered safely, survived key rotation and mixed-version rollout, or rehearsed canary rollback.

`platform_wire_production_gate.py` closes that repository-validation gap. A transport/deployment owner supplies a frozen plan and raw observations from one registered workflow. The validator checks exact identities, closed scenario coverage, resource ceilings and failure semantics. It does not infer external truth merely because JSON is well formed.

## Closed producer registry

`PRODUCTION_PRODUCERS.json` is the only producer/plan registry accepted by the protected intake. A registration binds:

- one exact same-repository workflow path;
- one exact artifact name;
- one immutable production-plan SHA-256;
- one target-host profile;
- one deployment profile;
- one accountable owner;
- an explicit enabled flag.

The registry is intentionally empty in this source candidate. Existing fixture-provider tests, loopback gateway tests, in-process release probes and the protected source target-host workflow are not silently promoted into deployed production observations. Enabling a producer requires an ordinary reviewed source commit that names the real deployment workflow, immutable plan and selected profiles. Dispatch inputs select a registration; they cannot create or widen one.

## Artifact contract

A registered producer uploads one artifact containing exactly these regular root files:

- `production-plan.json`, schema `hepta.platform-wire.production-plan.v1`;
- `production-observations.json`, schema `hepta.platform-wire.production-observations.v1`.

The plan freezes exactly eight scenarios, each scenario's procedure digest, minimum attempts and required assertions. The report binds the exact candidate SHA, exact plan bytes, release/deployment artifact digests, configuration digest, host and deployment profiles, toolchain, runner, deployment identity and canonical producer run identity:

```text
github-actions:<owner/repository>:<run-id>:<run-attempt>
```

The report also binds non-loopback transport context: network scope, peer-identity scheme, authenticated channel-binding profile and key-domain provenance. Fixture, mock, loopback, in-process or unknown identities cannot qualify.

## Required scenarios

The scenario set is closed and must be complete:

| Scenario | Required production facts |
|---|---|
| `authenticated-ingress` | non-loopback transport, verified peer identity, authenticated channel binding, verified key provenance and rejected unknown peer |
| `gateway-provider-e2e` | existing gateway, consumer and provider paths used; final-use authority revalidated; terminal outcome observed |
| `bounded-pressure` | connection, transport queue, consumer retention and active-fragment ceilings enforced; at least 100 pressure observations; RSS observed |
| `deadline-cancellation` | deadline enforcement, pre-admission cancellation, post-admission reconciliation and zero blind retries |
| `reconnect-restart` | fresh session identity, no in-place sequence reset, truncated partial record rejection and no replay of unknown effects |
| `key-rotation-retirement` | fresh key domain, old-session rejection, retired-key unusability and unchanged admission policy during rotation |
| `mixed-version-rolling` | V2 interoperability, explicit compatibility policy, downgrade rejection and an observed multi-step rolling window |
| `canary-rollback` | canary health observation, rollback trigger rehearsal, preserved evidence and no manual lifecycle promotion |

Every scenario retains attempts, completed operations, zero unexpected failures, all required assertions, one scenario artifact digest, one raw-log digest and scenario-specific metrics. Resource observations must not exceed the plan/report ceilings. Recovery, rotation, downgrade, canary and rollback counters must show that those paths actually ran rather than being declared vacuously.

## Protected intake workflow

`.github/workflows/platform-wire-production-intake.yml` is operator-dispatched and runs in the `platform-wire-production` environment. It requires:

1. the exact candidate SHA, equal to the dispatched ref head;
2. a successful same-repository producer run ID;
3. the exact registered producer workflow path;
4. the exact registered artifact name;
5. the registered frozen plan SHA-256.

The workflow verifies that the producer was an exact-source `workflow_dispatch` success and that exactly one unexpired artifact with an immutable SHA-256 belongs to that run. It rejects artifacts over 20 MiB from metadata, records the immutable GitHub artifact digest, and downloads the exact named artifact from the exact run through the pinned official download action. After extraction it accepts exactly the two expected root regular files and enforces independent 256 KiB and 16 MiB limits for the plan and report. Missing or extra entries, directories, links and oversized inputs fail closed; the receipt binds the GitHub artifact digest plus the exact plan and report byte digests.

After archive admission, the workflow runs the closed producer registry check and the eight-scenario validator. It emits a `hepta.platform-wire.receipt.v2` receipt of kind `platform-wire-production`. The receipt binds source, workflow/run/attempt, artifact/archive identity, registry, plan and report digests, deployment artifacts/configuration, transport context and all eight reduced outcomes. Failed attempts retain a failed receipt and available metadata; they never become acceptance.

## Lifecycle integration

Source qualification remains exact-head plus deterministic synthetic merge plus protected target-host evidence. Production acceptance is stricter. `scripts/platform_wire_status.py` now requires all of the following before `Accepted` can become true:

- `Qualified` is true;
- one passed five-path `platform-wire-performance` receipt for the same source;
- one passed eight-scenario `platform-wire-production` receipt for the same source;
- one independent semantic/security reviewer receipt;
- one distinct operations receipt.

`Released` additionally requires the existing source-bound release receipt and artifact digest. Performance and production composition are separate gates: a fast but unauthenticated deployment fails, and an authenticated deployment that misses either frozen performance ratio also fails.

## What remains external

This source adds the closed contract, validator, protected intake, lifecycle requirement and failure-preserving evidence path. It does not supply the external observations. Production owners must still:

- review and register the actual deployment observation workflow and immutable plan;
- run it against the selected real gateway/provider deployment and target host;
- retain authentic peer/exporter/key-domain provenance and raw scenario evidence;
- run the separately registered five-path gRPC comparison;
- issue independent reviewer and operations decisions;
- perform canary/promotion and issue the release receipt.

No second authenticator, transport listener, scheduler, authority owner, replay journal or domain executor is introduced. Wire admission and production observation never mint final-use authority. Lifecycle booleans remain derived and must not be edited by hand.
