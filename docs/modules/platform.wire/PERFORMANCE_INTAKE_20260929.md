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

`scripts/platform_wire_performance_gate.py` recomputes p99 from retained raw samples and uses exact integer comparisons. It requires distinct measured artifact digests for the candidate and gRPC reference, preventing a report from presenting one binary as both sides of a comparison.

## Closed producer registry

`PERFORMANCE_PRODUCERS.json` is the only producer/plan registry accepted by the protected intake. A registration binds:

- one exact same-repository workflow path;
- one exact artifact name;
- one immutable plan SHA-256;
- one host profile;
- the `grpc` reference transport;
- one accountable owner;
- an explicit enabled flag.

The registry is intentionally empty in this source candidate. The existing cloud throughput workflow and in-process release profiles are not silently promoted into production benchmark producers. Enabling a producer requires an ordinary reviewed source commit that registers the real paired product-path workflow, artifact, plan and host profile. Duplicate, disabled, unregistered or context-drifting selections fail closed.

A dispatch input is therefore only a selector. It cannot create a registration or widen the allowed performance surface.

## Producer artifact contract

A registered benchmark/transport owner uploads one artifact containing these exact regular files at its root:

- `performance-plan.json`, schema `hepta.platform-wire.performance-plan.v1`;
- `paired-measurements.json`, schema `hepta.platform-wire.paired-measurements.v1`.

The plan contains exactly five unique `path_id` values, one immutable workload digest per path and a bounded minimum sample count. The report binds the exact candidate source SHA and the exact bytes of the plan. It names the release profile, gRPC reference, registered host profile, runner identity, toolchain and canonical producer run identity:

```text
github-actions:<owner/repository>:<run-id>:<run-attempt>
```

Every path retains candidate and reference package sizes, distinct artifact SHA-256 identities, raw latency samples, completed-operation counts and zero failed operations.

The producer owns the truth of its host, transport, packaging boundary, deployed binaries and workload execution. The repository validator checks registration, internal consistency and thresholds; it cannot infer those external facts from JSON alone.

## Protected intake workflow

`.github/workflows/platform-wire-performance-intake.yml` is deliberately separate from the ordinary cloud-runner throughput probe. An operator dispatch supplies:

1. the exact candidate SHA, which must equal the dispatched ref head;
2. the successful same-repository producer run ID;
3. the exact registered producer workflow path;
4. the exact registered artifact name;
5. the registered frozen plan SHA-256.

The intake runs in the `platform-wire-performance` environment. It verifies that the producer run:

- belongs to this repository;
- was started with `workflow_dispatch`;
- completed successfully;
- names the selected registered producer workflow path;
- has the same exact candidate SHA;
- exposes one unexpired artifact with an immutable SHA-256 and the same source identity;
- has a positive run attempt matching the report's canonical run identity.

The workflow does not hand the archive to a generic extractor. It rejects artifacts larger than 20 MiB from metadata, downloads the ZIP through a bounded stream, verifies the SHA-256 of the exact downloaded archive against GitHub's immutable artifact digest, inspects the central directory and permits only stored or deflated regular files. Exactly two root entries are allowed, with no duplicate, directory, encrypted, linked or auxiliary entry. The plan and report are then read under their own 256 KiB and 16 MiB ceilings, CRC-checked by the ZIP reader and written into a private temporary directory before semantic validation.

After archive admission, the workflow validates the registry selection and runs the five-path gate. It emits a `hepta.platform-wire.receipt.v2` receipt of kind `platform-wire-performance`. The receipt binds the source, registry, registered owner, producer repository/run/attempt/workflow, artifact identity, plan and report digests, paired environment, thresholds and all five reduced path results. Failed intake attempts retain a failed receipt and available metadata; they never become acceptance.

The workflow does not accept arbitrary refs, arbitrary same-repository workflows, unregistered plans, averages that hide a bad path, the ordinary in-process probes, or fixtures as production measurements.

## Lifecycle integration

Source qualification is unchanged: `Qualified` still requires exact-head, deterministic synthetic-merge and protected target-host receipts for one source candidate.

Production acceptance is stricter. `scripts/platform_wire_status.py` requires all of the following before `Accepted` can become true:

- `Qualified` is true;
- one passed `platform-wire-performance` receipt for the same source;
- one independent semantic/security reviewer receipt;
- one distinct operations receipt.

`Released` additionally requires the existing source-bound release receipt and artifact digest. A missing, failed, malformed, stale or source-inconsistent performance receipt blocks `Accepted` and `Released` without changing `Qualified`. This preserves separation between source/host qualification, measured performance, independent review, operations approval and release.

## What remains external

Adding this intake closes a repository-controlled evidence gap; it does not supply the evidence itself. The following facts still require their existing owners and real execution:

- review and registration of the five product paths and gRPC reference artifacts;
- a producer workflow that performs the actual paired runs on the selected target host;
- real authenticated ingress with independently established peer, exporter/channel-binding and key-domain provenance;
- integrated gateway/provider queues, deadlines, cancellation, backpressure and connection limits;
- reconnect, process restart, key rotation, rolling upgrade and mixed-version observations;
- independent reviewer, operations, canary/promotion and release decisions.

No lifecycle boolean should be edited by hand. Run the status renderer with the retained exact-head, merge, target-host, performance, reviewer, operations and release receipts for the same selected source.
