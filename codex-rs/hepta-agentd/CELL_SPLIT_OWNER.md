# Cell Split V1 — explicit execution owner (P0 increment)

## Boundary

The Rust owner is in src/cell_split_owner.rs. It is deliberately **not**
installed in canonical Agentd startup, and its trait is **not** a mock
implementation of product effects. It cannot perform a real split until a
separately reviewed product composer supplies ALL live adapters below.

A CellSplitPlanV1 is immutable and binds split/scope/cell ids, the exact parent
and successor generations, the two immutable artifact IDs and their content
digests, migration, independently selected evaluation, and an exact Final-use
binding. The artifact IDs are NOT Cell IDs or candidate IDs. The independently
signed Artifact Owner's `storage_binding` is also frozen separately from the
Split's logical scope digest; a CURRENT view from another storage namespace is
rejected before any payload is consumed. The distinct
`selected_candidate_id` is bound to the plan and its operation keys; a new
child Cell ID must never be inferred to be the evaluator's candidate ID.
`verify_current_child_artifact` consumes the real learning-artifacts
`RevalidatingCandidate` and an owner-issued `VerifiedCurrentRegistryViewV1`;
it checks the separately pinned child artifact ID, parent artifact lineage,
generation and actual loaded content digest against an authenticated current
registry. The function grants neither CAS write nor promotion authority.
The plan also freezes the exact Objective digest, no-change baseline ID/digest,
held-out dataset digest, and minimum future-window duration. It refuses a
selection receipt from another objective/baseline/dataset or with an inadequate
future observation window, even if its candidate and parent IDs happen to match.
`verify_selected_candidate` checks the existing opaque
`VerifiedSelfEvolutionSelectionV1` (signed evaluator, observer, selector and
future-window validation) against BOTH identities, generations, artifacts and
the accepted selection digest. It does not create selection authority. A digest is context, **not**
authorization. Only the process holding the one locked file may drive a split.

The durable order is:

1. ArtifactCas: create-only Artifact CAS publication + authenticated readback
2. StateMigration: real child checkpoint commit + authoritative readback
3. ShadowChild: child bootstrap in shadow, not production traffic
4. IndependentSelection: observe an independently signed, future-window
   evaluated selection; this executor cannot create it
5. FinalUseReady: observe a live independently signed final-use grant for this
   exact split/scope/generation; the executor cannot create it
6. SupervisorFence: durably disable parent generation writes
7. CnsRouteCutover: reverify the exact accepted selector receipt and
   signed Final-use evidence, check/consume Final-use at the real effect boundary,
   and compare-and-swap the CNS route against the pinned parent generation

The informational `progress().completed` flag is false until all seven
accepted receipts have been independently acknowledged by the observer at
the exact terminal head. An accepted final ledger frame with a lost observer
ACK is *not* completed; a re-entry must revalidate every real owner before
advancing the observer. Progress is never itself production authority.

Every step first durably records pending intent. It then obtains a current
authoritative readback. The executor may issue mutation only after an
authoritative Missing observation, using the exact deterministic operation
key. It commits only real owner evidence that the separately trusted port has
authenticated. **Before every external mutation**, the owner requires a
successful `retain_ledger_anchor` acknowledgement for the already-durable
pending-intent frame from an independent, rollback-protected observer. After
each real receipt, it requires another observer acknowledgement before
running a subsequent mutation. Earlier acknowledged prefixes are revalidated
before observer reconciliation, so a recovered but unverified suffix is not
automatically blessed.

A timeout, lost ACK or unknown outcome is Indeterminate, never success,
and cannot be treated as Missing. The next owner resumes by reading
the external owner first; it must not replay effects blindly.

On all re-entries, previous accepted steps are checked against current
authoritative state and their retained raw receipts; drift fails closed.
Selection and final-use remain external and cannot be auto-issued. Cutover
receives the two exact retained external evidence bodies and must verify
freshness, revocation and one-time consumption against independent authority
at the mutation boundary. A once-valid grant may become spent: after cutover,
`observe` must verify its signed issuance/consumption history rather than
requiring the grant to remain unconsumed. Cutover is never treated as completed
merely because a candidate graph digest exists.

## Ledger and recovery

The host MUST supply a fresh read/write regular file under a trusted private
root, with an exclusive OS lock for the owner lifetime, and must retain a
**signed/authenticated anchor in a separate rollback domain**. The file cannot
self-certify its recovery checkpoint. Bootstrap requires an empty file and explicitly resets its cursor to the
header start; recovery requires the exact plan and an external anchored ledger
prefix. The only public recovery entrypoint is `recover_from_observer`, which
queries a `CellSplitRecoveryObserverV1` for an independently verified anchor.
A raw journal-derived `CellSplitLedgerAnchorV1` is never accepted directly by
product callers.
Valid suffixes past an earlier anchor survive lost-ACK recovery. Incomplete
crash tails can be trimmed after verifying every complete predecessor frame.
Complete invalid frames, mixed scopes or lost anchored history block recovery.
A live owner rereads the complete bounded, hash-chained ledger before
dispatching any effect, retaining an observer anchor, or appending a receipt.
It compares the actual header, every complete frame boundary, and every frame
digest against the previously authenticated in-memory chain. Out-of-band
truncation, extension, **or same-length byte replacement** poisons the owner
and prevents further effects; a separate trusted recovery decision is required.
Recovery allocates and reads only the previously validated <=256 KiB physical
length and rejects an inode that grows during read. No read-to-EOF allocation
is permitted on untrusted recovery input. Advisory locks are NOT protection
against a hostile writer who can bypass the trusted filesystem boundary.

Each frame commits the full bounded raw external receipt, the deterministic
operation key and generation, a predecessor frame head, and a checksum.
No caller may treat the hash chain alone as trusted witness evidence.
The host is responsible for directory durability, witness persistence and
an independent signature/trust/revocation check.

## Still required before production activation

- Implement the live CellSplitExecutionPortsV1 adapter using the real
  LearningArtifactOwnerService / CAS bytes and its signed publication/current
  head verification; never fabricate receipt bytes from a proposed digest.
- Perform per-child native state migration and persistent checkpoint commit
  with actual Neuron/state owner acknowledgement.
- Bind launch + health/readiness to the real child process and existing
  Supervisor generation fence (including CAS expected predecessor).
- Verify independent self-evolution selection and Final-use signatures
  with separate keys; consume final-use in the CNS cutover owner, not here.
- Use the actual CNS route CAS and durable ledger observer anchor. Validate
  recovery when cutover succeeded but its ACK was lost.
- Add a named Agentd startup composition that supplies the above owners,
  fail-closed readiness, observer, and recovery loop.
- Run the real owner integration tests, strict Clippy, fmt, global CI, then
  execute target-machine crash injection. Until all gates pass, remain
  shadow-only and refuse physical Cell Split production promotion.

## Qualification

Run after the Rust toolchain (1.95.0) is available:

    cd codex-rs
    cargo test -p codex-hepta-agentd --lib cell_split_owner
    cargo clippy -p codex-hepta-agentd --lib --tests -- -D warnings
    cargo fmt --all --check

The test ports in cell_split_owner_tests.rs are explicitly qualification-only
deterministic fixtures. They do NOT count as signed CAS, Supervisor, CNS,
NDU, or host-performance receipts.
