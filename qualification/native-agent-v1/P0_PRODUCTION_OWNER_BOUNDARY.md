# P0 native production composition boundary

## Claim and evidence status

The product API and controlled owner path are connected. Ordinary CLI production
closure remains **held on the real composition/evaluation source**. This note is
a source audit and a definition of acceptance scope, not a passing test receipt.
Execution receipts must name the final candidate source and binary. Results from
an earlier candidate cannot qualify later context-policy or startup-gate changes.

Source locations below refer to the reviewed 2026-10-30 snapshots; symbols remain
the reference after formatting. No new grant issuer, evaluator signing key,
authority store, or test-derived production provider is introduced.

## Existing product entry and the remaining composition boundary

`native_product_bootstrap.rs::AgentdCanonicalNativeCompositionV1` and
`run_native_product_with_loader` (lines 33-82 and 117-129) consume the embedding's
existing runner, invocation provider, recovered writer, operations, and native
configuration. They enter the original `crate::run` once. That is an embedded
product entry. `hepta-agentd/src/main.rs` (lines 12-183) still builds the ordinary
configuration and calls `run` directly; its authority-file flags install only an
intelligence runner. They do not install the production invocation provider,
evaluation trust, recovered writer, or native composition.

`state.rs::start_canonical_intelligence` (lines 598-643) asks the host provider to
build inputs for the **original durable RunStart**, validates that identity, and
uses the original deadline. `intelligence_ingress.rs` (lines 15-60) is already the
minimal provider interface. The reviewed repository inventory located only
`objective_queued_fixtures.rs::CanonicalObjectiveTestOwners` (line 308) as its
implementation. Adding another forwarding trait would not provide owner state.

The irreducible missing input is independently authenticated evaluation for the
actual use. `AgentdIntelligenceOwnerInputsV1` (`intelligence_product.rs:198-213`)
requires current utility, neuron, prompt, intuition, context, and evaluation
inputs. Its evaluation stage (lines 514-549) requires signed evaluation; an
unsigned request cannot produce a ready native run. The signature binds the
original run, objective, snapshot, compiled context, candidate set, and selected
candidate (`intelligence_evaluation.rs:43-72,85-143`). The evaluator principal must
also match the current `learning.eval` owner key. AuthBus authentication and a
FinalUse grant authenticate different boundaries and cannot substitute for it.

The host must provide a pinned learning root and its existing signed signer
distribution to `activate_learning_trust`
(`hepta-learning-ledger/src/trust_distribution.rs:107-183`), then attach the
resulting `ActivatedLearningTrustV1` with `with_evaluation_trust`
(`intelligence_product_runner.rs:34-43`). Activation verifies signature, scope,
validity and monotonic rotation; it does not create a signer. The authority JSON
is a freshness source, not the seven owners' profiles, model state, or evidence.

## Reusable factories and their limits

All Agentd paths in this table are under `codex-rs/hepta-agentd/src/`.

| Existing source | Reusable capability | Input still supplied by the real host |
| --- | --- | --- |
| `prompt_runtime.rs:530-566`, `AgentdPromptPipelineOwner` | Reopen the durable prompt registry/runtime and enumerate its real candidates | Enumeration request and independently selected/compiled policy inputs |
| `plasticity_process_bootstrap.rs:268-343`, `load_plasticity_process_bootstrap_v1` | Pin the descriptor and identity; reopen ledger, NDU and anchored neuron journals | Existing descriptor, independent anchors and actual runtime inputs; this is not a seven-owner invocation factory |
| `intuition_policy.rs:66-96,111-167`, `AgentdIntuitionPolicyHostV1` | Pin existing verifier/model/scorer/RNG identities and verify an actual decision | Request, policy, scoring/assignment commitments and qualification evidence |
| `cognitive_retrieval_context.rs:16-22` | Existing current-context interface | Authenticated model/prompt/encoder/profile/engram generations; the file defines a trait, not a source implementation |
| `production_writer_host.rs:272-313`, `open_with_recovery` | Recover the exact independently retained cut and retain the live writer verifier | Original recovery requirement, authority lease, live verifier and lease identity |
| `production_grant_provider.rs:26-106`, `AgentdUnixFinalUseGrantProvider` | Request a bound grant from an existing Unix issuer | Existing socket, issuer identity and registered FinalUse authority; no evaluator or seven-owner state is supplied |

The inventory also located the supervisor's `H7H89ProductionGrantVerifier`.
Absence of a non-test invocation provider is not a claim that all production
verifiers are absent. The remaining work is to connect the actual deployment
composition source to the existing interfaces, preserving its original roots,
leases, evidence and recovery cuts. Until that source is supplied, a default
file full of fabricated profiles or fixture signatures is not a valid loader.

## Startup rejection for missing evaluation trust

The candidate adds a crate-private `evaluation_trust_configured()` observation
and checks it in `AgentdConfig::validate_native_composition` only for
`CanonicalObjective`. A freshly constructed runner has no evaluation trust;
the daemon now rejects that incomplete composition before runtime setup. This
checks **configured presence only**. It does not establish current trust,
evaluator availability, a valid signature for the next task, or deployed readiness.
Per-task verification remains unchanged.

`native_bootstrap_rejects_missing_evaluation_trust_before_runtime_setup` uses the
actual `new()` default, enters `crate::run`, and requires zero provider/attach
calls, an unchanged recovered-writer anchor, and unopened control/app sockets.
It also preserves non-native compatibility. This test still requires a passing
receipt from the final candidate; static patch review is not execution evidence.

## Four controlled acceptance scopes

The opt-in entry names are fixed in
`native_runtime_acceptance_fixture.rs:21-24`. All four use controlled external
authorities/model or transport. A passing result in one scope does not qualify
the other scopes or an ordinary deployed CLI.

| Entry | Acceptance boundary | Not established by this test |
| --- | --- | --- |
| `controlled_native_process_acceptance` | Real original jobs/helper/child/output and cancel; original writer/FinalUse, queue/checkpoint/history, success/cancel/terminal race, and a complete two-model-call/one-tool-call turn | Live production model, ordinary daemon startup, controller OS restart, authenticated SSH/systemd; the report marks controller restart false and SSH/systemd held |
| `controlled_signed_objective_process_entry_gates` | Signed Objective through the original owners/Core queue; revoke or expire before tool entry; original tool remains indeterminate, same durable job/key is observed, zero tool child/launch/nonce and no recreated operation | Successful production task execution, actual SSH/systemd, a new production invocation provider |
| `controlled_original_terminal_checkpoint_continuations` | Continue after actual model-terminal or tool-terminal checkpoints, or reconcile the same Created-only model response by GET before continuing; preserve the checkpoint prefix and original queue binding; one explicit recovery/typed successor, two total model POSTs, one actual child, and retained non-UTF8 raw output evidence | OS restart, ordinary CLI bootstrap, authenticated SSH/systemd, or active process cancellation; the stop is injected through the original checkpoint owner or a pending response |
| `controlled_embedded_daemon_lifecycle` | Typed loader into the real daemon, UDS startup/readiness, signed Objective, one model response, original queue/history/provenance, idempotent replay, drain and isolated daemon shutdown | Ordinary CLI bootstrap, authenticated SSH, OS restart, in-flight tool cancellation or pending tool continuation; the compiler emits no tool and the sole transport process is the health probe |

Source anchors: `native_runtime_acceptance_tests.rs:258-281` and
`native_runtime_full_turn_tests.rs::exercise`; `objective_native_process_gate_tests.rs:112-232`;
`objective_native_terminal_continuation_tests.rs:88-173,284-400`;
`native_daemon_lifecycle_tests.rs:179-446`. The daemon report explicitly records
`ordinary_cli_bootstrap_qualified=false`, `ssh_authentication_qualified=false`,
and `os_restart_qualified=false`.

Runtime's separate real SSH/systemd restart/cancel/long-output canary and the
same-job output ABBA measurements retain their own evidence scope. They do not
turn these controlled composition fixtures into a deployed product demonstration.

Context policy v3 is likewise a separate admission gate: serialized host/tool
items are capped at 8 KiB and requested output at 1..=8192 tokens. Byte caps do
not prove tokenizer limits, and old pending operations retain their original
configuration/body/key rather than migrating into the new policy.
