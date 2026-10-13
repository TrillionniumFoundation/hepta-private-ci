# Proposal-only compiled computer-use Cell

`codex-hepta-compiled-use` is an experiment scaffold for the local hot path
described in Experiment 6. It defines a 256-byte, digest-bound ABI for five
typed actions:

* read the accessibility tree;
* click;
* type bounded UTF-8 text;
* scroll; and
* capture a bounded region.

`ActionVerifierV1` checks the generation, capability grant digest and action
mask before `SharedMemoryQueueV1` accepts a frame. The queue is bounded and
sequence-fenced. The current backing is process-owned `VecDeque` storage with
the same fixed-frame contract; an OS shared-memory adapter can be added later
behind the ABI without putting unsafe code or pointers in this crate.

`propose_compiled_use_v1` packages a verified, consecutively numbered action
list into a deny-all `CompiledUseProposalV1`; `verify_compiled_use_proposal_v1`
rebuilds its digest before it can be handed to an independent sandbox owner.

There is no machine-code field, executable-memory writer, dynamic loader or
OS effect. `DenyByDefaultSandboxV1` always rejects submission. A real product
caller must first obtain `VerifiedActionV1` from the verifier, then supply an
independently reviewed sandbox implementation of `SandboxActionPortV1`, bind
it to the existing authority/capability plane and retain rollback/audit
evidence.

Run the safe smoke runner with:

```text
cargo run -p codex-hepta-compiled-use --example compiled_use_runner
```
