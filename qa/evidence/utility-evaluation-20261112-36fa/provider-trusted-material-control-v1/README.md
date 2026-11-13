# Original Material control inputs — isolated test proposal

This four-file increment preserves the original Material construction and adds
a bounded comparison codec for test control. It has not been formatted,
compiled or executed. Source/ref `cc57` is unchanged.

The original fixture's complete Root-signed trust distribution and activation
body moves into `original_fixture_trust_at`. Its return includes both the
original `ActivatedLearningTrustV1` used by the one `LedgerWriter` and a clone
of the full host-owned `LearningEvidenceTrustV1`. The existing `ledger_at`
signature remains, delegates to the same body, and discards only that clone.
There is still one actual ledger create and one writer, with the same original
files, binding, witness, root signature and validity windows.

The original unstarted Material body also retains the already computed update
scope/rule and the exact payload passed to the one original freeze signature.
Its existing entry point remains a delegate with the same two returned values.
The new provider builder fields retain those inputs and full trust; no Stage
Execute, Dataset read, clock sample or signature is added. The static report
inversely reconstructs both original function bodies byte for byte.

`ParentMaterialControl::from_original` takes a previously held typed Material
config, the independent full host-owned trust and the original constructor
inputs. It constructs the verifier only from that trust, verifies the original
complete freeze payload/signature, re-freezes the original request/owners and
compares the whole scope. The control schema has no signer-list or trust-source
field. The original 8 KiB canonical snapshot codec retains all seven original
owner IDs and the complete request, bundle, profile, envelope, budgets and cut.
The control datagram retains the existing harness's 64 KiB bound.

Decode requires canonical bytes and equality with all pre-held inputs before
returning a cloned typed config with the decoded full snapshot. It does not
renew a freeze, choose a new trust state, open a file or create an owner. A
valid newly signed freeze is still a different input and is rejected.

One new, unexecuted mechanism test uses the actual Fresh unstarted same-A
fixture. It constructs the expected full trust before the provider and codec,
round-trips all original inputs, rejects canonical changes to the full request,
scope, rule, original freeze fields/payload/signature, actors, limits and trust,
and checks the fixture's explicitly enumerated original bytes before/after.
It does not assert conservation of an unenumerated filesystem inventory.

## Remaining assembly work

This is a strict replay/comparison codec, not first-time provider admission.
The dual-UID caller still must hold the original typed inputs independently
before invoking it. The complete 60002-owned A/Material construction and its
first trusted transfer to Root cannot be replaced by a child's digest report.
That assembly must bind the parent's preselected objective/profile/budget,
the original Source and signed freeze, actual peer identity and existing role
channels. No native two-UID harness is invoked by the new codec test. The
full ten-owner, same-C daemon and Root recovery scenario is still incomplete.

The exact existing Native harness remains a separate immutable source
`c269e4c7adfefb3853ea67ca46197af049dd4cbc`. Its credential readiness and metadata
transport are not learning results. No real authorized A/B/C chain, measured
utility or gate PASS is claimed by this proposal.
