# Independent runtime source review

The reviewer authored the process/reference harness, separately from the Rust implementation. The numerical reference uses supplied reference matrices and SciPy `expm`; it does not call the Rust propagation routine or a project transition method. The record checker uses the Python standard library and no project helpers. This is a bounded implementation review, not a production security proof.

## Information and numerical execution

The owner entry point opens its MODEL, public PLAN, owned snapshot and endpoint. It does not receive or open CATALOG, REFERENCE, a posterior successor tape, or a teacher action value. The provider alone opens CATALOG. READ/REFRESH tokens enter `apply` only after a real TCP reply has been parsed and bound to the current planned action. `apply` computes the posterior in Rust. The financial MODEL contains only three parameters; its Q, emissions and initial prior are constructed by Rust. The generic profile intentionally accepts explicit model matrices.

RESET first sends each content marginal into recovery phase zero and then evolves the entire supplied interval. The independent reference applies the same explicit task semantics using a different matrix-exponential implementation. An actual final-token intervention keeps the public MODEL/PLAN unchanged, changes the provider's returned observation, and requires a posterior change of at least .01. That control distinguishes a live numerical callback from an opaque precomputed after-state replay.

## Crash invariants

An owned snapshot contains the complete FP64 posterior bits, applied plan cursor, integer time, applied fees, applied receipts and at most one pending paid-action index. Before CALL, the owner persists that pending index. The provider checks the complete run/model/plan/action/fee context and atomically persists the actual effect before acknowledging it. An exact retry returns the existing receipt. The owner then computes its successor and atomically persists posterior, receipt, cursor, time and applied fee in one snapshot.

Conditioned on the declared trusted local filesystem and unchanged executable artifact, this supplies an induction over the applied plan prefix: a death before a state commit retains the previous prefix and repeats the same deterministic numerical operation with the same durable observation; a death after a commit resumes at the next cursor. The process tests check this at actual marked boundaries. They do not prove behavior at arbitrary fsync-internal instructions or machine power loss.

SYNC uses a fresh TCP connection on each owner invocation. The remote ledger must equal the applied owned prefix, plus at most its single pending effect. Missing owner state with paid remote effects and a lost provider prefix both reject. These checks prevent the tested one-sided state-loss cases from silently repeating a charge. They cannot detect a coordinated rollback of both ledgers without an external witness.

## Artifact and context binding

The model identity includes explicit numerical semantics ABI bytes, raw MODEL bytes, canonical constructed Q/emission/prior FP64 words, and the exact executable artifact fingerprint. `identify MODEL` exposes that public identity for PLAN preparation. Source inspection verifies all four inputs are included. A copied executable with added nonexecuted bytes is tested to reject an old PLAN and, after PLAN rebinding, an old owned checkpoint. A byte-identical executable copied to a new path must remain compatible. The altered-artifact control is not an independently changed numerical ABI experiment.

FNV checksums are trusted-profile consistency checks. They do not provide collision resistance, provider authentication or resistance to malicious writers. The executable file and filesystem are assumed stable while a process is running. Cross-artifact migration and production model lifecycle remain unqualified.

## Billing and limits

Applied owner fees do not count an already paid but unapplied provider effect. An impossible observation intentionally leaves provider fee25, owner applied fee0 and durable pending index1. The negative is reported as incomplete execution with a paid pending cost; it is neither a free attempt nor a successful recovered answer.

No finding here establishes analytic-core D−B, learned policy quality, real multimodal binding, energy advantage, cross-host ownership, authenticated transport or production admission. Those gates retain their own evidence requirements.
