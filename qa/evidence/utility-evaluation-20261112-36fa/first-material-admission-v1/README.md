# First Material report: private Pending preparation

Status: prepared Rust source only. No formatter, compiler, Rust test, H command, source gate, native phase, source commit or ref update was run for this package. It does not establish a real useful A/B/C chain or a completed three-UID Root deployment.

## What this layer implements

The parent first holds `PreheldMaterialInputs`: its complete typed task policy, original panel registration, full host-owned evidence trust and signers, loaded baseline, original task input/NDU identity, fixed outcome unit, optimizer, scope, freeze plan ID and original limits. The report has no trust or signer-set field. This contract deliberately has no invented completed-task receipt.

The new wire accepts one canonical JSON frame with a total 64 KiB limit, including all base64 and metadata overhead. It uses the unchanged original 8 KiB owner-snapshot codec and the independently reviewed complete LedgerSnapshot codec. It rejects missing, truncated, noncanonical, unknown-field and oversized data. This fixture profile requires the entire two-event authenticated Decision/Outcome history; it never filters a larger ledger into a convenient subset.

The verifier reconstructs the complete original Decision, including its retained completeness object, and the complete Outcome, using the parent's pre-held Observer principal. It verifies both original signatures at their same retained signing/append times and at fresh time. It compares every authenticated ledger event field, controller, credential, key, scope, epoch and signature digest with those original proofs. It uses the original role-separation and outcome validators. Neither causal replay nor an authentication digest alone is accepted as a signature.

The complete decoded ledger and parent's fixed plan produce the original freeze-signing payload. The original Evaluator signature is verified without renewal. The original dataset receipt, exact Q32-to-Q24 target, host-selected source input, optimizer and frozen scope are recomputed with the existing pure APIs. Fresh time, original work expiry and signatures are checked again after that work. The parent's full request, owners, evaluation profile, envelope and cost budget must match the decoded initial cut exactly.

The received `completed_task_receipt` remains a Pending claim. A valid freeze signs that exact claim through the original initial head and inclusion policy, but the report cannot construct `CircuitTaskSourcePublicationV1`. There is no Source, Material or Training getter on `PendingOriginalMaterial` and no second writer or live-ledger recovery.

## Existing Root path, without new authority

Pending can request the existing canonical `RootResidentLearningProfileV3::admission_binding`; this is public binding data, not authorization. `profile_with_original_authorization` accepts the caller's already signed original Root intent and already registered lease. It invokes the existing profile constructor and neither signs nor installs those artifacts.

The only effectful exit consumes Pending, an already existing `RootResidentLearningRegistrationV3`, the original ten-role handoff and the original consumer into the existing `into_candidate_service`. That service still checks Root authority before and after channel admission, binds the original handoff deadline and composes the original runtime. Runtime's actual fresh CAS installs the original effect gate. It executes Experience, verifies and commits its original evidence, then does the same for Dataset before Training can be dispatched. Original E/D owners read their actual Source/ledger/full freeze and D rereads Source/current; absent or mismatched material remains refusal/Unknown. No readback failure is changed into an Execute fallback here.

## Mechanism validation prepared in source

One new local mechanism method uses the actual Fresh A fixture and the original signatures retained by dependency `d656853ee0fb0e4bf7aedbd371916607d7dcb619`. It prepares a typed parent contract before encoding the report, obtains the original binding, and checks signature/context substitution, incomplete candidates, full controller trust, budget and input replacement, expiry, changed completion claim, a causally valid re-encoded but unauthenticated ledger, extra trust, trailing bytes and the aggregate size limit. The test retains original cleanup and compares original files. It has not been executed.

This local test's parent can already access its trusted fixture task inputs, including the original envelope. It is explicitly not evidence that a separate UID has yet received those inputs through a completed first-admission orchestration. The separate three-UID parent must supply the same complete pre-held values from its own original configuration, without deriving policy from the report. The old `ParentMaterialControl` replay helper is not used as first admission.

## Remaining implementation and validation

- Compose the actual three-UID parent/children with pre-held task/envelope/model/actor inputs, the complete bounded first report, actual Root authorization and all original connected roles. That orchestration is still being written; this package does not claim it is merely waiting to run.
- Prove the original Root CAS/E/D failure and success paths with the actual public role services. The local method does not run Root service or E/D/T.
- Complete same-A FinalUse, Version, same-C daemon ingress and Root recovery composition. Existing staged and local mechanism fixtures do not substitute for that test.
- Run the original formatter, complete source collector/QA, and required native phases under the sole native executor when its existing process guard permits. Preserve all original quotas, stack and budgets. No result from older snapshots is inherited.

Base: Root's exact 86-path overlay `3f7d40d4933669da33d2aef3491efb431c5771ae`, plus the explicit original-evidence retention dependency. Ledger codec dependency is `3a7aee950bc6da48b4162f4f5215c4c5d18396b8` followed by `487e202226d32f9b7e98238703f66015fec59aae`. The only changed existing file is the resident-provider test parent, with one appended child mount. No production file changes are in this layer.
