# DecisionCell target-host evidence

`CellSplitTargetHostHarnessV1` is a source simulation fixture. It is useful for
negative-path tests, but its reports cannot qualify a production target host.
Production qualification uses the signed envelope implemented in
`cell_split_target_host_evidence.rs`.

A target host exports a canonical JSON `CellSplitTargetHostEvidenceV1` payload
with an append-only event chain. The payload includes a target-host attestation
digest; this is a digest of hardware/host identity evidence supplied by the
external deployment owner, not a value inferred by the source harness. The payload must contain, in order:

1. child artifact load;
2. route cutover with predecessor fence;
3. restart recovery;
4. power-loss recovery, including a fault-injection witness digest;
5. rollback to the predecessor;
6. child tombstone commit; and
7. no-resurrection verification.

Resource events can be interleaved with the lifecycle events. A resource event
contains CPU, GPU, or NPU counters, a hardware model, an attestation digest, and
a non-simulation measurement source. The verifier rejects `fixture`,
`simulation`, and source-simulation origin markers.

The target-host owner signs the canonical payload with Ed25519. At least one
independent observer signs the exact same bytes. The acceptance process supplies
trusted host and observer keys out of band; public keys embedded in the JSON
are not trusted by themselves. Verification then checks the schema, generations,
artifact binding, event sequence, hash chain, lifecycle ordering, signatures,
resource measurements, and all required witnesses before issuing
`CellSplitTargetHostProductionReceiptV1`.

The optional `CellSplitTargetHostLifecycleRunnerV1` is only an orchestration
seam for a deployment-owned implementation of
`CellSplitTargetHostRuntimeV1`. It orders the real artifact, CNS, restart,
power-loss, rollback, tombstone, no-resurrection and resource-owner calls and
returns an **unsigned** event payload. It does not implement any of those
owners, derive a receipt from a digest, or issue a production receipt. A host
adapter must supply the immutable operation receipts and an independent
observer must sign the resulting canonical payload before the verifier can
accept it.

The JSON API is:

```rust
verify_cell_split_target_host_evidence_json(&bytes, &trust_policy)
```

It is intentionally the only path to a production receipt. Reports from the
source simulation harness remain useful for tests, but they cannot be upgraded
by setting a production boolean or by adding a digest.

## External ingest and durable store command

The `hepta-operator-acceptance` binary exposes the same verification boundary
for a deployment-owned target host. The host exports the signed envelope; the
operator supplies a separate, externally pinned trust policy containing the
trusted public keys:

```json
{
  "schema": "hepta.learning.cell-split.target-host-trust-policy.v1",
  "schemaVersion": 1,
  "hostKeys": {
    "host-signer": "<base64-ed25519-public-key>"
  },
  "observerKeys": {
    "observer-signer": "<base64-ed25519-public-key>"
  }
}
```

The key values are raw 32-byte Ed25519 public keys encoded with standard
base64. Private keys never belong in the policy file. The embedded public keys
inside the evidence envelope are checked against this policy and are not
trusted on their own.

Verify an evidence file without storing it:

```text
hepta-operator-acceptance target-host-evidence verify \
  /absolute/path/target-host-evidence.json \
  /absolute/path/target-host-trust-policy.json
```

`ingest` is an alias for `verify`. Evidence can also be streamed over stdin:

```text
cat /absolute/path/target-host-evidence.json | \
  hepta-operator-acceptance target-host-evidence ingest - \
  /absolute/path/target-host-trust-policy.json
```

Verify and durably store the exact canonical signed envelope:

```text
hepta-operator-acceptance target-host-evidence store \
  /absolute/path/target-host-evidence.json \
  /absolute/path/target-host-trust-policy.json \
  /absolute/path/verified-target-host-evidence.json
```

The command first verifies the complete lifecycle, signatures, hash chain,
resource measurements, and trust policy. It then performs a private atomic
replace and reopens the stored bytes during the write path. A failed
verification never writes a production receipt. The command does not create
host or observer signatures, infer hardware counters, execute CNS cutover,
simulate power loss, or convert a source-simulation report into production
evidence. The JSON printed on success is the verifier-issued
`CellSplitTargetHostProductionReceiptV1` and can be attached to the external
TaskFlow and learning-ledger records.
