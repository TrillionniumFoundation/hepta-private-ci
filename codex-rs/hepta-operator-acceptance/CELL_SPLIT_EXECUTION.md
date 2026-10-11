# P0 Cell Split: pinned, one-effect execution

This entry point is a **coordinator**, not a model runtime, authorization issuer,
production promoter, or substitute for a target-host witness. It calls four
independently pinned Unix effect services in strict order:

1. Artifact CAS creation and immutable artifact confirmation
2. Durable, all-child state migration publication
3. Authentic CNS cutover with the predecessor writer already fenced
4. Supervisor writer-handoff journal retirement confirmation

The command delegates to `CellSplitExecutionOwnerV1` and
`CellSplitUnixEffectPortV1`. Each execution owner must enforce its own current
Selector/NDU and final-use checks, maintain an idempotent durable effect key,
and expose signed current-state readbacks. The four public keys and sockets
must belong to independently controlled effect owners.

## Trusted configuration

The deployment owner must prepare a **private**, canonical, absolute-path JSON
file (Unix mode `0600`). Its exact SHA-256 must be supplied *out of band* by
the independently controlled deployment selector. Deriving a fresh "trusted"
hash from a possibly tampered local file does not establish trust.

Configuration shape (`<...>` are placeholders, not runnable credentials):

```json
{
  "schema": "hepta.learning.cell-split.execution-cli.v1",
  "plan": {
    "splitId": "<frozen-split-id>",
    "scopeDigest": "<sha256>",
    "parentGeneration": 1,
    "childGeneration": 2,
    "parentArtifactDigest": "<sha256>",
    "childArtifactDigest": "<sha256>",
    "nduSnapshotDigest": "<sha256>",
    "routeFenceDigest": "<sha256>",
    "ownerIds": [
      "<artifact-owner>",
      "<migration-owner>",
      "<cns-owner>",
      "<supervisor-owner>"
    ]
  },
  "executionRoot": "/private/canonical/existing-split-state",
  "ownerSocketPaths": [
    "/run/hepta/artifact-owner.sock",
    "/run/hepta/migration-owner.sock",
    "/run/hepta/cns-owner.sock",
    "/run/hepta/supervisor-owner.sock"
  ],
  "ownerVerifyingKeysHex": [
    "<32-byte-ed25519-public-key-in-lowercase-hex>",
    "<different-pinned-public-key>",
    "<different-pinned-public-key>",
    "<different-pinned-public-key>"
  ],
  "timeoutMillis": 5000
}
```

The `executionRoot` must already exist as a private real directory;
`CellSplitExecutionOwnerV1::open` verifies its filesystem identity, locks it,
and refuses conflicting frozen-plan or journal data.

## Commands

Use the externally supplied pin; do **not** synthesize it from the file at
execution time.

```sh
hepta-operator-acceptance cell-split-execution advance \
  /private/canonical/cell-split-config.json "$PIN_FROM_INDEPENDENT_OWNER"

hepta-operator-acceptance cell-split-execution transcript \
  /private/canonical/cell-split-config.json "$PIN_FROM_INDEPENDENT_OWNER"
```

An `advance` invocation calls at most one effect. It persists the exact
prepared intent before entering the physical owner. On an unknown or lost
acknowledgement, it returns a non-success result. A later invocation reads
the original owner state via `reconcile`, never retransmits that effect.
The CLI cannot bypass the coordinator's journal lock, predecessor binding,
or verification of original owner signatures.

`transcript` performs no mutations: it requires the existing locked
execution directory and frozen plan and never initializes missing state. A
query against an uninitialized split root fails instead of creating a plan or
lock. It reports a complete four-receipt transcript only after re-reading the
current original state and verifying each pinned owner; otherwise the
transcript is absent or the command fails. A pending prepared intent is
rechecked for drift even when there are no completed receipts.

An independently controlled observer can call
`verify_cell_split_execution_transcript_signatures_v1` with its own
externally pinned `CellSplitOwnerTrustV1`. This recomputes the frozen-plan
digest, exact four-step predecessor/idempotency chain, per-owner Ed25519
signatures, receipt digests, and the final transcript digest. It rejects
reordered, missing, forged or modified receipts without invoking an effect.
This is **offline cryptographic consistency only**: it does not establish
that an effect is still current, authenticate a target host or witness
power-loss recovery. Production acceptance separately requires fresh
nonce-bound readbacks from the four original owners, independent Selector/NDU
admission, host and observer evidence, and future-window evaluation.

The output always sets `productionActivationAuthorized: false`. Completion
does not constitute an independent host attestation, real CNS/Agentd
composition proof, signed deployment authorization, power-loss witness,
no-change NDU improvement, future-window retention, or a 16-case performance
qualification. All remain separately enforced production gates.

## Native source checks

```sh
cargo test --locked --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-operator-acceptance --lib cell_split_execution
cargo check --locked --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-operator-acceptance --all-targets
```

No source-only test or mock socket is a production deployment receipt.
