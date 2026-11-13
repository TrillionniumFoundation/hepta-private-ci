# Fresh Training to original B fixture component

This is an isolated, test-only component for the resident-provider proposal. The fixed source base is `cc57c7198db6293ccca562253c42fffbe2a04633`, tree `b7b357c07b5539769a068c6b9b009629f5612d1e`. The eight Rust postimages remain exactly those in `MANIFEST.initial.json`. Nothing has been applied to the native checkout; no Rust compilation, formatting, test, or source gate has run for this component.

The new path starts with the actual Fresh Bootstrap's completed T and its original Candidate material. It does not run `PositiveFixture::ready_for_publication` or an auxiliary Evaluation/Model to obtain the inputs. Existing tests retain the old `PanelMemberFixture::complete` path and the original negative outcome assertions.

## Integration sequence

1. Obtain the real fixture A admission and its objective/trust time. Construct `PreparedBPanel::new(objective, trust_time)` and pass its registration into the unstarted original Material request before its first signature or T execution.
2. Create `OriginalTrainingPeers::new(Arc::clone(&bootstrap), material.clone())` while the same original Bootstrap is still unstarted. It owns one Candidate and two original Training readback transports with the unchanged 300-second fixture lifetime and original peer policies. It serves the same actual Bootstrap; no canned completed response is installed.
3. For the staged fixture, await the real original Training execute result. Bind the consumed Candidate connection with actual D, the returned opaque original T and the original loaded baseline; read Candidate material from that connection. Bind the two separate Training readback connections to the same actual D/T.
4. Construct `CompletedTrainingInputs::from_original_completion` from the actual Material/D/T/Candidate, original loaded baseline, original A publication/source/configuration and fixture credentials. It checks the complete T receipt/signature pair against opaque Candidate material, the actual three-cut prefix, baseline components, A objective/run/history binding, and the actual owner principals. It derives the candidate and baseline manifests from those original models and bundles.
5. Call `PreparedBPanel::complete(inputs, primary_trainer, retention_trainer)`. The retention member is completed first; its original qualification digest enters the primary declaration. Both use the real B Source/Cell/ledger providers, runner and original Qualification owner. The existing equal-policy result remains `Ineligible`. The method returns a real original Evaluation host but does not execute the Evaluation command.
6. Keep `OriginalTrainingPeers` alive while B, Evaluation, Version and other actual consumers retain their clients. Close/join external service futures, then finish or recover `CompletedBPanel` through its original owner API. Finally call `OriginalTrainingPeers::finish`, which shuts down all owned socket handles and joins every server thread, returning actual handler counts or an error. Drop is best-effort cleanup and never produces a successful count.

Bootstrap `Ready` is deliberately not used as a T completion signal. The original Bootstrap installs Ready before calling the original Training Execute handler. A full autonomous Root test must observe the actual completed T or the real recorded three-cut checkpoint before it reads the preheld Candidate/evidence channels. An early Candidate read can consume/close that connection. A separate completion-observer increment, if prepared, must preserve this eight-file snapshot.

## Exact scope and old behavior preservation

Five existing files are append-only: the Bootstrap ports, command connection support, readback connection support, owner-support parent mount and evaluation-provider parent mount. Their complete original bytes are retained as prefixes.

`BFixture` gains explicit completed-training input methods. The old wrappers supply the same original publication, baseline/candidate digests, scope, T signature and verifier. The original common source-execution bodies and assertions are preserved under those explicit parameter substitutions. The old pure training snapshot construction now occurs in the wrapper before the configuration body; it creates no owner, signature, side effect or new authority.

`PanelMemberFixture::complete` directly returns the common future with `None`; the old signature-backed fixture responder is constructed only in that branch with the same arguments. The new `complete_from_original_trainer` supplies `Some(actual_client)` and leaves that server owned by `OriginalTrainingPeers`. All original execution, Qualification, receipt/signature and `Ineligible` assertions remain. The public wrappers return the common future directly and do not add an outer async-state copy.

`review_preservation.py` checks all seven preimages against the complete canonical inventory. It uses only two original lexical masking definitions, not verifier main or caller collection. It proves the five byte prefixes and the two common-body equivalences after the listed explicit substitutions. This is source-byte analysis, not a Rust AST or type check.

## Test-only and lifetime boundaries

All new constructors are located in existing test-only module chains. No production trait, wire, owner constructor, execution admission, signer, credential issuer, deadline, cost contract or permission surface changes. The cloned raw sockets are test teardown handles; they are not production FD getters. Connections are consumed once and keep their initial binding and age.

The existing B fixture uses explicit independent labels, keys, task data and a fixture clock at `trust_time + 124`. The actual Bootstrap signature lifetime is 300 seconds. These mechanisms are not evidence of an externally supplied independent B task, unbiased outcome data, real utility, or a deployed ordinary loop. `Ineligible` remains an honest mechanism result under the existing equal-policy inputs; this component creates no positive claim or Adopt path.

Socket shutdown cannot roll back a previously admitted remote operation or force a blocked original owner operation to complete. Normal/EOF/cancellation/join behavior must be checked by the actual integration tests with the original budgets. No timeout or stack limit is changed here.

## Integration dependencies and unverified items

The new owner-support mount names `circuit_resident_candidate_provider_material_support_tests.rs`, which is supplied by ordinary_path's separate v2 proposal. This component is not standalone buildable until that companion file and its module consumers are present.

Rust name resolution, generic/lifetime typing, Send requirements, combined fixture stack behavior and all actual service lifecycle behavior remain uncompiled and unexecuted. The static review does not resolve them by assumption. The same-process internal three Training links do not stand in for the ten public Root/owner streams: those still require the actual original peer/pidfd/UID transport and complete integration cases.

`CompletedBPanel::recover` requires all external host Arcs to be released and uses the original on-disk owner recovery. A failed custody/Arc precondition is an error, not permission to rebuild fresh state. Missing/uncertain evidence must continue to reject through the original production checks.

No active source, native input, Git ref, PR, qualification result, or evidence cutoff is changed by this component.
