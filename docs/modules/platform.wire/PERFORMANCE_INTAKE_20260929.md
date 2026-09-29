# platform.wire protected paired-performance intake

Date: 2026-09-29. This document defines a repository-controlled evidence intake. It does not manufacture target-host measurements, authenticate an unregistered benchmark producer, issue independent review, activate a deployment or release an artifact.

## Why this gate exists

`platform.wire` already has release-built in-process probes for decoder throughput, managed sessions, multi-peer scheduling and retention policies. Those measurements are useful regression evidence, but they are not the required five-path comparison against the reference gRPC transport and they do not represent an integrated gateway/provider deployment.

The production performance contract remains per path, not an average across paths:

- candidate package bytes / reference gRPC package bytes must be `<= 0.70`;
- candidate p99 latency / reference gRPC p99 latency must be `<= 0.80`;
- exactly five frozen paths must be present;
- each candidate/reference pair must retain at least 100 raw latency observations;
- failed operations, missing samples, path substitution, workload drift or candidate/reference artifact reuse fail closed.

`scripts/platform_wire_performance_gate.py` recomputes p99 from retained raw samples and uses exact integer comparisons. It now also requires distinct measured artifact digests for the candidate and gRPC reference, preventing a report from presenting one binary as both sides of a comparison.

## Producer artifact contract

The benchmark/transport owner must first register one producer workflow and one frozen performance plan. A successful operator-dispatched run of that workflow uploads one artifact containing these exact regular files at its root:

- `performance-plan.json`, schema `hepta.platform-wire.performance-plan.v1`;
- `paired-measurements.json`, schema `hepta.platform-wire.paired-measurements.v1`.

The plan contains exactly five unique `path_id` values, one immutable workload digest per path and a bounded minimum sample count. The report binds the exact candidate source SHA and the exact bytes of the plan. It names the release profile, gRPC reference, host profile, runner identity, toolchain and producer run identity. Every path retains candidate and reference package sizes, distinct artifact SHA-256 identities, raw latency samples, completed-operation counts and zero failed operations.

The producer owns the truth of its host, transport, packaging boundary, deployed binaries and workload execution. The repository validator checks internal consistency and thresholds; it cannot infer those external facts from JSON alone.

## Protected intake workflow

`.github/workflows/platform-wire-performance-intake.yml` is deliberately separate from the ordinary cloud-runner throughput probe. An operator dispatch supplies:

1. the exact candidate SHA, which must equal the dispatched ref head;
2. the successful same-repository producer run ID;
3. the exact registered producer workflow path;
4. the exact artifact name;
5. the frozen plan SHA-256.

The intake runs in the `platform-wire-performance` environment. It verifies that the producer run:

- belongs to this repository;
- was started with `workflow_dispatch`;
- completed successfully;
- names the selected producer workflow path;
- has the same exact candidate SHA;
- exposes one unexpired artifact with an immutable SHA-256 and the same source identity.

It then downloads that exact artifact, applies byte and symlink bounds, runs the five-path validator and emits a `hepta.platform-wire.receipt.v2` receipt of kind `platform-wire-performance`. The receipt binds the source, producer run, producer workflow, artifact identity, plan and report digests, paired environment, thresholds and all five reduced path results. Failed intake attempts retain a failed receipt and available metadata; they never become acceptance.

The workflow does not accept arbitrary refs, average away a bad path, substitute the ordinary in-process probes, or use a fixture as a production measurement.

## Lifecycle integration

Source qualification is unchanged: `Qualified` still requires exact-head, deterministic synthetic-merge and protected target-host receipts for one source candidate.

Production acceptance is now stricter. `scripts/platform_wire_status.py` requires all of the following before `Accepted` can become true:

- `Qualified` is true;
- one passed `platform-wire-performance` receipt for the same source;
- one independent semantic/security reviewer receipt;
- one distinct operations receipt.

`Released` additionally requires the existing source-bound release receipt and artifact digest. A missing, failed, malformed, stale or source-inconsistent performance receipt blocks `Accepted` and `Released` without changing `Qualified`. This preserves separation between source/host qualification, measured performance, independent review, operations approval and release.

## What remains external

Adding this intake closes a repository-controlled evidence gap; it does not supply the evidence itself. The following facts still require their existing owners and real execution:

- registration of the five product paths and gRPC reference artifacts;
- a producer workflow that performs the actual paired runs on the selected target host;
- real authenticated ingress with independently established peer, exporter/channel-binding and key-domain provenance;
- integrated gateway/provider queues, deadlines, cancellation, backpressure and connection limits;
- reconnect, process restart, key rotation, rolling upgrade and mixed-version observations;
- independent reviewer, operations, canary/promotion and release decisions.

No lifecycle boolean should be edited by hand. Run the status renderer with the retained exact-head, merge, target-host, performance, reviewer, operations and release receipts for the same selected source.
