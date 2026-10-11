# Cell Split V1 — explicit execution owner (P0 increment)

## Boundary

The Rust owner is in src/cell_split_owner.rs. It is deliberately **not**
installed in canonical Agentd startup, and its trait is **not** a mock
implementation of product effects. It cannot perform a real split until a
separately reviewed product composer supplies ALL live adapters below.

A CellSplitPlanV1 is immutable and binds split/scope/cell ids, the exact parent
and successor generations, the two artifacts, migration, independently selected
evaluation, and an exact Final-use binding. A digest is context, **not**
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
7. CnsRouteCutover: check/consume final-use at the final-use boundary and
   compare-and-swap the real CNS route against the pinned parent generation

Every step first durably records pending intent. It then obtains a current
authoritative readback. The executor may issue mutation only after an
authoritative Missing observation, using the exact deterministic operation
key. It commits only real owner evidence that the separately trusted port has
authenticated. A timeout, lost ACK or unknown outcome is Indeterminate, never
success, and cannot be treated as Missing. The next owner resumes by reading
the external owner first; it must not replay effects blindly.

On all re-entries, previous accepted steps are checked against current
authoritative state and their retained raw receipts; drift fails closed.
Selection and final-use remain external and cannot be auto-issued. Cutover is
never treated as completed merely because a candidate graph digest exists.

## Ledger and recovery

The host MUST supply a fresh read/write regular file under a trusted private
root, with an exclusive OS lock for the owner lifetime, and must retain a
**signed/authenticated anchor in a separate rollback domain**. The file cannot
self-certify its recovery checkpoint. Bootstrap requires an empty file;
recovery requires the exact plan and an external anchored ledger prefix.
Valid suffixes past an earlier anchor survive lost-ACK recovery. Incomplete
crash tails can be trimmed after verifying every complete predecessor frame.
Complete invalid frames, mixed scopes or lost anchored history block recovery.

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
