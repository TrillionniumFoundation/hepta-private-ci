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

## Original-owner durable frontier

The signed effect service compares the original owner's **intent-scoped**
durable sequence before and after `Execute`. A freshly committed effect must
advance that sequence; a previously committed matching effect must not be
adopted as a new execution.

- Artifact CAS starts at its independently frozen sequence-one predecessor
  frontier. Only an exact, create-only, intent-bound committed CAS record
  advances the acknowledged sequence to two. A copied artifact without that
  record is an ambiguous orphan, not a committed step.
- Child-state migration starts at the acknowledged parent Neuron checkpoint
  sequence *N*. Only a verified all-child batch marker for the exact intent
  advances its acknowledged sequence to *N+1*. Staged Q24 children or an
  interrupted multi-child write do not advance it.
- CNS and Supervisor retain their native monotonic durable sequence/revision
  readers; they must never substitute an in-memory callback count.

The source candidate changes the CAS receipt sequence from the earlier
non-advancing value. Pre-existing, non-monotonic receipt frames must **not**
be silently rewritten or grandfathered into successful Execute evidence.
They require original-owner reconciliation under an independently controlled
deployment plan. None of this constitutes a cross-owner atomic transaction,
physical power-loss witness, or production acceptance.

## Trusted configuration

The deployment owner must prepare a **private**, canonical, absolute-path JSON
file (Unix mode `0600`, one physical link; hard-linked aliases are rejected). Its exact SHA-256 must be supplied *out of band* by
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

### Frozen owner trust continuity

The coordinator writes `cell-split-owner-trust-pins.json` once under the
same exclusive execution-root lock as the frozen plan. This record binds the
plan digest, four exact owner IDs and four independently configured Ed25519
verifying keys. Every `advance` and `transcript` checks the exact canonical
bytes again, including after reopening the process.

Missing or modified pins **never trigger automatic rekeying** once the
frozen plan exists, even before the first prepared intent or external effect.
If both immutable identity frames disappear, the pre-existing execution-root
sidecar lock also prevents silent reinitialization. Incomplete initialization,
a mismatched key, missing file, noncanonical committed receipt or dangling
journal frame blocks execution and requires independent recovery review.
Do not delete the affected history, regenerate a new trust pin from local
inputs, rename the same effect under a new Split ID, or replay a possibly
executed mutation to bypass the block.

This is local continuity protection, not defense against deletion or rollback
of the **entire** execution root including its lock. The independently pinned
configuration and an externally retained witness remain mandatory; neither
a local lock nor this coordinator can recreate lost owner truth.

The locally frozen pins only prevent unnoticed changes to this coordinator's
trust identity. They do **not** establish independent custody or authorization:
the selector must still supply the externally pinned config hash and each
effect owner must prove current signed state on every readback.

## Commands

Use the externally supplied pin; do **not** synthesize it from the file at
execution time.

```sh
hepta-operator-acceptance cell-split-execution advance \
  /private/canonical/cell-split-config.json "$PIN_FROM_INDEPENDENT_OWNER"

hepta-operator-acceptance cell-split-execution transcript \
  /private/canonical/cell-split-config.json "$PIN_FROM_INDEPENDENT_OWNER"
```

An `advance` invocation calls at most one effect. For a new step,
it first requires a fresh, nonce-bound, signed **negative readback** from the
original effect owner. Missing/unreachable owners or an already committed
effect cannot cause an otherwise new `prepared` intent to be written. This
read-only preflight is not a final-use authorization, nor proof that a future
mutation will succeed. After that preflight, the coordinator durably writes
the exact `prepared` intent **before** entering the physical mutation. On an
unknown or lost acknowledgement, it returns a non-success result. A later
invocation reads the original owner state via `reconcile`, never retransmits
that effect or repeats the new-effect preflight.
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

### Artifact CAS object-before-commit recovery

An on-disk child artifact is not sufficient proof of an accepted CAS operation.
The object may have been fully copied and fsynced just before the process died,
without writing the original, idempotency-key-bound commit record. Even when its
SHA-256 matches the frozen child artifact, a subsequent `Execute` must return
an ambiguous outcome and must not create a replacement commit receipt.
`ReadBack` remains non-authoritative until the original commit can be
independently verified; the execution coordinator never resends a prepared
intent. Recovery needs an independently approved reconciliation procedure,
not an opportunistic adoption of orphan bytes.

### Signed CNS → Supervisor predecessor bridge

The third coordinator step and the original CNS runtime retain **different**
commitments. The coordinator's signed `CellSplitExecutionReceiptV1.receipt_digest`
is the *outer* digest consumed as step four's
`previous_receipt_digest`. The Supervisor writer-handoff journal's
`cns_cutover_receipt_digest` binds the exact *inner* original runtime
receipt bytes. Treating these two hashes as interchangeable cannot establish
a production predecessor.

The opt-in Supervisor adapter exposes
`CellSplitSupervisorJournalRuntimePortV1::new_with_signed_cns_predecessor`.
It verifies the original step-three CNS effect-owner signature under an
independently pinned key, reconstructs the exact coordinator predecessor,
parses the signed typed CNS commit, checks its generation, epoch, idempotency
key, durable sequence and successor route, and binds its original runtime
bytes to the existing Supervisor journal commitment. The underlying
`CellSplitFinalizationAuthorityV1` must independently reread the live CNS
route, NDU/Selector frontier and final-use authorization. A signed outer
envelope alone does not prove the cutover is still serving.

The old identical-digest `new` constructor is **test-only**. Production
builds must use the signed two-layer bridge and still require a real CNS
runtime owner, independent signer custody, durable ledger and target-host
recovery witnesses. This source adapter is not a production activation
grant.

### CNS frozen-binding loss and recovery

The CNS cutover owner now treats the persistent sidecar-lock identity as an
initialization marker. If that lock already existed but the frozen CNS binding
has disappeared, `open` rejects reinitialization **even while the signed
predecessor route is still serving**. A previously prepared plan cannot be
silently replaced by another one merely because no child cutover has occurred.
Retain the original owner files and reconcile their state with the independent
CNS writer; do not delete the lock to suppress this error.

This local anti-reinitialization check is not an independently retained
anti-rollback witness. Deletion of both the lock and frozen binding cannot be
proved from the remaining local directory alone. Production acceptance must
still check independent CNS/Selector frontiers and signed route/retirement
witnesses, including after restart and physical power loss.

## Opt-in Agentd selected-plan ingress

Agentd now has an opt-in `cell-split-operator-bridge` Cargo feature,
**disabled by default**. The caller
`advance_selected_cell_split_v1` accepts an opaque independently verified
`VerifiedSelfEvolutionSelectionV1`, a signed NDU snapshot read and the
Control-owned `NduReadVerifierV1`. After the operator configuration's
external SHA-256 pin is verified but **before** the coordinator is opened,
it checks the selected Split identity, predecessor/child generations,
predecessor/child artifact digests and NDU snapshot digest, and re-verifies
the signed NDU read against protected time and the current Control frontier.

If this preflight rejects, it prepares no intent and invokes no effect owner.
A selection receipt is **not** a final-use grant. The four independent
effect services must still authenticate current Selector/NDU and one-shot
final-use at their own mutation/readback boundaries. The current bridge is
a callable source ingress, not a canonical startup composition or live
deployment registration. The exact selected candidate-to-child route
association, CNS durable cutover, independent observer evidence and
target-host power-loss/recovery qualification remain unproven.

Targeted source check:

```sh
cargo test --locked --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-agentd --features cell-split-operator-bridge \
  --lib cell_split_execution
```

## Native source checks

```sh
cargo test --locked --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-operator-acceptance --lib cell_split_execution
cargo test --locked --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-operator-acceptance --lib cell_split_artifact_cas
cargo check --locked --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-operator-acceptance --all-targets
```

No source-only test or mock socket is a production deployment receipt.
