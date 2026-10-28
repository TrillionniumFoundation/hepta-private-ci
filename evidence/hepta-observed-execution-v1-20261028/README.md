# Original-model observation execution and ordinary-install readiness

This independent successor preserves the frozen metadata-only tree
`ee2776d9c032ecb6e44e8f1a480af299dea7b3b9`. It introduces an explicit execution
profile for the existing public V2 model contract. It does not turn the
historical strict-v1 third-round failure into a pass or issue a model credential.

## Execution composition

The original Rust three-round owner still owns CURRENT reads, child process
groups, the 2,700-second campaign guard and reaping. The original Python round
still owns candidate training, all four controls, scoring and unqualified hold.
The original Chain parent-step owner still starts the same training child and
verifies the exact parent and trained factors. The new frozen observation plan
selects the already implemented `linux-owned-exit-worker-pidfd-v4` supervisor
policy. Candidate, all control children and all evaluations use that one policy.

The model plan and c9b06f9a target remain exact original bytes. The runtime source
remains `65ccc6454befd96fa5ce1f5bdde2c56cb6cbb741cf495b8d24a758039f99f755`.
Training retains ten steps, four CPU threads, 1,800 seconds and 16 GiB; inference
retains 600 seconds and 8 GiB; the host guard still requires 12 GiB. The observer
retains its original 100 ms drain limit and exact wait4/owned-child completion.

New request/attempt/actual/candidate/result, round freeze/assessment and loop
namespaces record the changed execution identity. Legacy requests and receipts
cannot relabel the new mode. Original c96022 material and descendant paths stay
on their original source; a separate exact Chain checkout serves only explicitly
observed rounds. No quality gate, control role or installed-child condition is
removed. The original post-gate research consumer recognizes the new loop only
after verifying all ten original phases and every ordinary CURRENT read.

The actual server dependency is Chain commit
`923de0b137bab71170a43910eddb25047a5b3266`, tree
`3c5037862f384765e9ff0f3831b60f094a5d7fe9`. This tree is exactly the frozen local
`8630dcf3dc28673a3020c7123e9c97563c5edfec` tree; server history uses the already
published 903517 parent. Both caller and CI checkout pin the actual server SHA.

The CI selector explicitly runs both the new eight Chain owner controls and
eight Hepta boundary controls before the full Rust build/test gate. Source checks do not count
as their remote execution: that requires real CI terminal records on this new
tree. Local Python validation passed 36 controls; the new Rust control has not
been executed locally. Full Rust/native/lint gates remain required on the actual
CI host. No new pretrained-model training or installation was run locally.

Local `just fmt` completed with the available Rust 1.95 / rustfmt 1.9.0 and
locked cached Ruff; Python AST hashes are identical across formatting. This is
not the repository's pinned Rust 1.96 verification. Its original CI gate remains
required and was not run locally. The earlier missing-workspace and missing-
rustfmt failures remain in separate raw logs; no tests were rerun after fmt.

## Actual hosted prerequisite failure

The new safe-tree run 40615280663 / job 122576208776 was still running when its
partial raw log was inspected. It had already produced 23 final-retry test
failures and 58 occurrences of `bwrap: loopback: Failed RTM_NEWADDR: Operation not
permitted`. The failures affect real sandboxed command execution and filesystem
helper operations; availability of the executable alone does not supply the
required user/network namespace capability. No job timeout was inferred from
the partial observation. `safe-ci-partial-summary.json` and the retained exact
failure lines record this lower bound, not a terminal full-gate result.

This successor runs the unchanged prerequisite argv from
`codex-rs/sandboxing/src/bwrap.rs`: `bwrap --unshare-user --unshare-net --ro-bind /
/ /bin/true`, with the same 500 ms bound. A real nonzero exit or timeout is a host
prerequisite failure. It stops a known unsupported host before expensive repeat
compilation; a capable host continues into every original full Rust, model and
ordinary gate. The probe is not the full gate. No sysctl, security switch,
sandbox environment variable, test skip or model resource budget is changed.
The existing required-outcomes verifier still refuses full acceptance if any
required Rust/native/lint outcome failed or did not execute.

## Source and output safety

The only additional exported evidence names are the observation source SHA/tree,
the separate plan, new input/result JSON, and the two control logs. They pass the
existing metadata validator. Safetensors, tensor-bearing JSON, hidden files,
payload archives and whole run directories remain excluded. Hash inventories
do not mean checkpoints were retained for independent replay. The previous
automatic rejection of checkpoint export remains in force.

## At least one real installed-child loop

Historical raw stage evidence contains real parent consumption, training and
evaluation in two rounds. Candidate and strongest control both scored 0.5,
giving gain 0. All subsequent ordinary reads retained generation-one CURRENT;
there were zero trained-child installations and zero complete requested loops.
The separate loopback Cell fetch and next-prompt forward used a different
unadmitted cohort and cannot be joined to those ordinary reads as one loop.

The required acceptance remains one continuous evidence chain: exact admitted
parent bytes, actual training and evaluation, cross-node acquisition, ordinary
installation under the existing selector, and the next task's readback of those
installed candidate bytes. A successful observed three-round no-update job
would prove more reliable execution of the original diagnostic, not that chain.

## Can two genuine SystemLongitudinal windows start now?

The inspected task inputs do not supply the independent host trust, preregistered
future dataset or live observation provider needed to begin qualified windows.
No windows were started, backdated, simulated, or signed in this work. The local
inventory is recorded in `longitudinal-readiness.json`; it makes no assertion
about unconnected external hosts.

The existing product path is concrete. `ProductEvaluationRunnerV1` freezes the
metric-to-estimator contract, consumes holdout under `FencedFinalHoldoutOwnerV1`,
calls the provider only after consumption, verifies signed time evidence, and
requires a durable publication. Product selection then binds exact candidate
and predecessor bytes to that sealed qualification and an independent selector.
The neural loader calls `require_product_qualification` and rechecks lifetimes
around ordinary consumption.

The process bootstrap is a replay path. `cognitive_process_product.rs` requires
an already nonempty acknowledged holdout, the same recorded plan and fence,
the pinned released inputs, and the pinned durable qualification. It refuses
using a descriptor to consume a new holdout. Source call-site inventory found
that this replay is the non-test caller of `evaluate_temporal_comparison`; no
configured live collection service was present in the inspected task material.

| Real input needed | Existing owner/contract | Current inspected state |
| --- | --- | --- |
| Host-selected trust root/distribution or independently pinned descriptor, scope/objective/authority epoch, role public keys, credential chains, controllers, validity and revocations | `hepta-learning-ledger/src/signed_evidence.rs` and `trust_distribution.rs` | No corresponding actual task input supplied; controlled test issuer does not qualify |
| Durable frozen candidate/baseline temporal plans, metric source mapping, dataset/snapshot IDs, exact future window set and host-selected minimum duration | `hepta-intelligence-eval/src/product_runner.rs` | Public smoke task freezes exist, but no independent future-data preregistration |
| Real live final-holdout provider and persistent CAS/fence/anchor outside learned-body paths | `fenced_holdout.rs`, `cognitive_process_product.rs` | No live owner/provider or independently retained anchor configured in the inspected task roots |
| Independent collection/clock provenance, positive observations from distinct source cuts in at least two actual windows | `longitudinal_time.rs` | No actual collection service, two window receipts or observer attestation supplied |
| Sealed temporal/OPE receipts, evaluator signature over exact V3 payload, retention/unlearning receipts and durable qualification publication | `ProductEvaluationRunnerV1::qualify_and_persist` | Absent; reported public gains are zero and grant none of this authority |
| Independent selector binding, exact source/registry/predecessor lineage, production neural ordinary consumer and next-task FinalUse | `self_evolution_product_selection.rs`, `neural_cognitive_ranker.rs` | Existing APIs are present; no installed qualified neural child |

Windows must begin strictly after freezing, not overlap, each meet the positive
minimum duration fixed by the host, have nonzero observations and distinct source
cuts, and end before both the observer's signed time and trusted current time.
The final holdout must be in the exact observed window set. Creating identifiers,
keys or waiting on a local timer does not provide these facts.

One additional execution integration boundary is visible: the ordinary CLI in
`hepta-agentd/src/main.rs` connects the tabular cognitive bootstrap. The exported
neural process loader and `with_evaluated_neural_cognitive_bootstrap` exist, but
that CLI does not yet select the neural family. This successor does not claim to
have connected it. Independent real inputs and that explicit integration must
be completed without bypassing the product qualification before a useful
ordinary neural installation can be accepted.
