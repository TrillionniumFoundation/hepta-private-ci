# Local execution under the inference.control owner

## Implemented boundary

`DurableInferenceControl::reserve_local`, `prepare_local`, `observe_local`,
`mark_local_indeterminate`, `cancel_local`, `begin_local_unload`, and
`observe_local_unloaded` use the SAME append/fsync journal and exclusive lifetime
writer lock as legacy and hosted native requests. There is no second worker
journal, authority issuer or device scheduler.

The `local-v1|` event family shares global record capacity and operation identity
with the existing event families. Identical request reuse returns the retained
record; drift in input, model tuple, resource ceilings, generation or absolute
deadline conflicts. Partial/corrupt events fail closed without truncation.

## Resource and failure semantics

A device lease pins its policy at first admission. Resident model bytes and
per-run KV/transient reservations are aggregated before dispatch, including
held records from predecessor generations. All arithmetic is checked.

Load: Reserved -> Dispatching -> Resident -> Unloading -> Released.
Run: Reserved -> Dispatching -> Succeeded / Failed / Cancelled.
Transport loss or process loss after prepare retains Dispatching/Indeterminate
and its reservation. Terminal observations may resolve uncertainty, but reopen
cannot create a new execution permit. Usage `None` is not `Some(0)`.

A failed load returning a physical handle remains Unloading and retains memory.
Unload failure performs no release. Runs holding a model prevent its unload.
Generation fencing survives journal reopen and denies new work, not cleanup.

`LocalDispatchPermit` is a non-cloneable, non-serializable live-process value.
Only a successful fresh prepare creates one. The live caller may consume it to
abort a definitely unentered effect; recovery cannot reconstruct that proof.
An expired deadline does not prove that previously dispatched work stopped.

## Trust and scope limitations

These are trusted-owner transitions, not cryptographic grant or hardware
verification. The physical caller must additionally verify the independent
kernel grant and consume its exact final-use token before the effect await.
A driver-provided correlation digest is not independently attested hardware.

The budget covers ONE opened control journal and its device-lease namespace.
Multiple independently created journals are not a global device reservation
service. Production composition must ensure one protected owner per physical
resource domain and independently establish OS/device accounting and isolation.

The current journal does not compact terminal identities. Exhaustion fails
closed. Retention/compaction must preserve deduplication and unknown operations;
copying, deleting or resetting a journal is not a recovery policy.

## Actual source-preparation evidence

Workflow run 36305134563, artifact 10926539293, preparation input
`72ea4ebd25afd2de5eb20a21ae3e81226f04d2ae`:

- actual macOS native inference.control library: 39 passed, 0 failed, 0 skipped;
- ten new tests cover replay, resource retention, cross-generation policy,
  unload failure, cancellation, identity drift, fencing, optional usage,
  exclusive ownership and partial-journal rejection;
- strict inference.control Clippy with all targets and `-D warnings`: passed;
- actual rustfmt source objects and Git/SHA-256 identities retained in artifact.

The explicitly integrated source objects are those tested and inspected bytes.
This is not final source-head/merge-candidate qualification of the whole worker,
Linux parity, physical local execution, production activation or independent
acceptance. The temporary preparation workflow/payload are removed on integration.
