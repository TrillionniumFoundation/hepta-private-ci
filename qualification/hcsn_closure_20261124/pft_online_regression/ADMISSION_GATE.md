# PFT admission regression gate: prospective extension

Base: `1a5a264c4eda7bf29e3e35ca7127402932721223` (#7211).
This extends the original 17-control maintenance protocol to exactly 20 controls.
It does not alter the earlier qualification entry point or historical results.

## Fixed scope

Keep LedgerTests (4), CodecTests (5), PeerTests (4), and BinaryPeerTests (4).
Add only AdmissionTests (3): one complete received-offer validation, refusal and
replay priority at capacity, and two actual receiver processes with concurrent
capped writers sharing one SQLite database. Preserve all existing assertions,
suite counts, fail-fast behavior, skip refusal, and numerical thresholds.

The admission module's BASELINE is loaded explicitly by the CI driver from
`pft_admission_validation/SYNTHETIC_SINGLE_OFFER.json`. Its full single_offer
object is copied unchanged from the first observed baseline.json in #7211's
retained attempt-1 archive, whose SHA256 is
`4e2f434043987965308f2b8b07cea1e7de1e867840e1801360966d98a60b0b48`.
The archive member is `baseline.json`, raw SHA256
`260c129ece72d865883cb676e7a642cce82de0f2f59585a940450d242c46889e`.
The fixture also records the original baseline and qualification source commits.
It contains synthetic identifiers and observations only; no private cache data.

Pin the fixture's raw SHA256 in the driver, archive its exact source bytes and
hash alongside all test dependencies, and recheck source integrity afterward.
The old two-validation/two-eigendecomposition counts remain observed reference
data. Routine CI never executes the old baseline, its unsafe capacity schedule,
or the original qualification CLI. AdmissionTests compares the complete new
receipt and packet identity to that reference and independently requires one
validation and one eigendecomposition for one received offer.

The seeded packet identity assertion is intentionally exact. If a different
runtime changes its bytes, preserve that failure; do not alter the fixture,
relax equality, or label a substituted reference as the original observation.
The original admission test source and its baseline/candidate CLI remain intact.

## Execution and evidence

Keep the current pinned actions, contents:read, exact event head, Python 3.12.3,
NumPy 2.3.5, one BLAS thread, 120-second test limit and ten-minute job limit.
Add workflow path triggers for the admission test source and fixed fixture;
keep the existing evidence-directory correction. Include the new test source in
the post-test Ruff 0.15.13 check. Retain the original protocol as historical
scope and capture this extension with each new run's source inventory.

Register this protocol and fixture before freezing the implementation and first
execution. Rehearse the new driver once on the local exact dependency capsule,
Python 3.12.14 / NumPy 2.3.5, with its real local Git head and source hashes.
This is a separate engineering integration check with a 120-second process-group
limit, not a hosted Actions result or full-repository checkout. Keep the first
outcome and any correction as separate attempts. Run official just fmt and Ruff
afterward, retain before/after AST evidence, and do not rerun local tests merely
for formatting. Continue read-only observation of the existing hosted run.

No original train caches, DEV/final data, E1-E6 budgets, model training or user
trajectories are used. A passing regression does not prove data authenticity,
global writer authorization, complete runtime closure, learning quality or
training acceleration. Keep runtime_closure_complete=false in runtime evidence.
