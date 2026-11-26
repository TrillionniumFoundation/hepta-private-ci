# runtime.codex deployment guide

This guide describes a target-host layout for the named runtime.codex caller.
It is a provisioning contract, not permission to deploy. The exact release must
already have current source qualification and must still pass target-host
qualification, independent acceptance, canary and rollback gates.

## 1. Service identities

Use separate non-login principals for:

| Principal | Owns | Must not own |
| --- | --- | --- |
| `hepta-agentd` | Agent generation, App Server process and ingress | issuer/quarantine signing keys |
| `hepta-codex-worker` | worker process and owner-private inference journal | App Server or issuer sockets |
| `hepta-final-use-issuer` | final-use decision and signing key | worker journal or provider output |
| `hepta-quarantine-authority` | signed quarantine resolution frontier | original operation execution |
| provider-audit exporter | read-only provider request audit export | runtime admission or signing authority |

A shared UID is not an acceptable process identity boundary. Where Linux
process-instance binding is enabled, pin the connected issuer's PID, process
start-time ticks, executable digest, cgroup digest and host boot-id digest, and
revalidate the process after each grant exchange.

## 2. Filesystem layout

Example only; replace with the selected host profile:

```text
/etc/hepta/runtime-codex/
  worker.json                 root:hepta-codex-worker 0640
  final-use-authority.json    root:hepta-codex-worker 0640
  release.json                root:root               0644

/var/lib/hepta/runtime-codex/
  journal/                    hepta-codex-worker 0700
  final-use-frontier/         hepta-codex-worker 0700
  quarantine-frontier/        hepta-codex-worker 0700
  evidence/                   root:root          0750

/run/hepta/
  agentd/<agent-id>.sock      hepta-agentd owned
  final-use/issuer.sock       hepta-final-use-issuer owned
```

Every ancestor of a trusted socket or protected state path must be checked for
unsafe writability and symlink substitution. State files require tested
`rename`/`fsync` semantics. Do not place durable frontiers on an unqualified
network filesystem.

## 3. Protected final-use configuration

The exact schema is defined by source; the following illustrates required
fields without supplying secrets:

```json
{
  "issuer_socket": "/run/hepta/final-use/issuer.sock",
  "issuer_uid": 12345,
  "signer_id": "runtime-codex-final-use-2026q3",
  "verifying_key": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
  "authority_state_dir": "/var/lib/hepta/runtime-codex/final-use-frontier",
  "authority_epoch": 1,
  "revocation_revision": 1,
  "revoked_grant_ids": [],
  "issuer_timeout_ms": 2000,
  "issuer_process_identity": {
    "expected_pid": 4242,
    "expected_start_time_ticks": 123456789,
    "executable_sha256": "<64 lowercase hex>",
    "cgroup_sha256": "<64 lowercase hex>",
    "boot_id_sha256": "<64 lowercase hex>"
  }
}
```

The private signing key is intentionally absent. A production configuration
with an all-zero example verifying key is invalid.

## 4. Binary and release identity

The release record binds at least:

- repository, source commit and source tree;
- ordered synthetic-merge parents and tree, when applicable;
- binary SHA-256 and build provenance;
- Rust/toolchain and dependency lock digest;
- target-host boot identity and service-unit/cgroup identity;
- Agent id and generation;
- App Server protocol/version and Codex home digest;
- issuer signer/process identity and authority/revocation frontier;
- provider account, endpoint and model identity;
- configuration digest;
- journal schema and anti-rollback checkpoint;
- rollback binary/configuration/frontier identity.

Reject an executable that is writable by the service user or whose digest does
not match the accepted release record.

## 5. Service hardening

Illustrative systemd properties; adapt them to the qualified host and required
App Server sandbox:

```ini
[Service]
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
UMask=0077
RuntimeDirectory=hepta-runtime-codex
StateDirectory=hepta-runtime-codex
```

Add only the filesystem, Unix socket, network and process capabilities actually
required by the selected profile. Do not silently relax sandboxing when a test
fails; record and independently approve any exception.

## 6. Startup sequence

1. Verify source and binary attestations against the accepted candidate.
2. Restore and validate external anti-rollback checkpoints.
3. Establish trusted time and revocation distribution.
4. Start the final-use issuer and capture its exact process instance.
5. Start the quarantine authority, if used on this host.
6. Start Agentd fenced and verify workspace, home, run root and generation.
7. Let Agentd create and own the App Server ingress.
8. Start the worker with admissions closed.
9. Verify journal schema/integrity, capacity and frontier monotonicity.
10. Verify issuer socket, connected peer and exact process identity.
11. Verify the model-only tool topology.
12. Run the protected target-host fault and performance qualification.
13. Run canary and rollback rehearsal.
14. Open admissions only after independent acceptance of the exact release.

Any identity or frontier mismatch leaves the service fenced.

## 7. Health contract

A healthy process is not automatically promotion-ready. Report separately:

- process alive;
- local durable store healthy;
- Agentd generation/ingress current;
- issuer process and frontier current;
- provider connectivity available;
- admissions open/closed;
- unresolved operation count and oldest age;
- quarantine count and oldest age;
- orphan-thread cleanup count;
- accepted source/target-host/independent evidence identities.

`ready=true` must not erase sticky owner loss for an already-started attempt.

## 8. Target-host qualification invocation

Use the protected workflow and external harness documented in
[`TARGET_HOST_FAULT_HARNESS.md`](TARGET_HOST_FAULT_HARNESS.md). The harness must
exercise all required scenarios against the built candidate and produce exact
source-bound JSON evidence. The real-provider sample is 30–200 operations,
default 50, with one unique physical provider audit record per operation.

Target-host evidence includes p50, p95, p99 and maximum latency, maximum RSS,
physical-request counts, durable journal digests and fault outcomes. These are
host-specific measurements, not universal service-level objectives.

## 9. Canary and rollback

Canary traffic is bounded by explicit operation count, concurrency and time.
Before widening traffic, prove:

- exactly one fresh server-owned fence winner per operation;
- at most one physical provider request;
- no post-fence abort;
- exact terminal correlation or retained unresolved ownership;
- stable p95/p99 resource behavior;
- no growth in orphan threads or unreconciled operations beyond policy;
- a successful rollback rehearsal that preserves all durable records.

Rollback never deletes journals, rewinds authority sequences or reuses an old
process/socket identity.

## 10. Secrets and logs

Keep private keys in the independently operated signer or hardware-backed key
service. Worker logs may contain stable IDs, registered reason codes and
cryptographic digests, but not:

- signing keys or bearer credentials;
- full prompts or unrestricted model output;
- raw memory/context content;
- unredacted provider responses;
- private quarantine evidence.

Route sensitive audit material to the separately governed evidence store.
