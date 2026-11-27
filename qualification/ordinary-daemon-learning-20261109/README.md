# Ordinary daemon learning composition — 2026-11-09

## Status and scope

This is an opt-in, one-iteration ordinary-runtime source integration. Production
acceptance remains **HOLD**. The CLI still lacks the real host stage-owner and
Circuit-provider assembly. This change creates no production Root capability,
training/evaluation service, selection or actual next-task use. Research owners
stay test-only; ordinary descriptor generation remains `Unpublished`.

## Ancestry

| Source | Exact commit | Reused portion |
| --- | --- | --- |
| #5430 baseline | `38c95265e8e549ff60fd88e1db5d3bf31b4264e7` | Root checkpoint UDS, Q24 factor graph and original owners |
| #5409 | `dafa66841cbcda56dcbab7f1a737514ec7e7fe4f` | Stage-owner contract and bounded protected checkpoint composition |
| #5433 M6 | `885dae0f3285267e9e9c49d8b43b0d009779f9e8` | Circuit outbox, history recovery, learning readback and delivery |

This selectively integrates related source, not every M6 change. Sibling test
results do not count as this candidate's validation. New work connects the real
Root client to stage owners, scopes queue admission, and supervises delivery.

## Ordinary-runtime behavior

The trusted host provides the original registered checkpoint or Root UDS client,
the actual stage owners, verifier and exact request. `with_stage_owners` binds
these inputs without creating a store, signer or capability. Restore reads
protected CURRENT and validates original stage recovery, including proposal and
independent anchor. The worker separately reauthenticates each signed receipt.

`with_circuit_learning_delivery(request)` installs one prebound request. The
ordinary `run_with_shutdown` requires Circuit and governed plasticity profiles,
retains the same learning channel and supervises `circuit-learning-delivery`
beside `learning-iteration-owner`. Only the configured source run enters the
original SQLite outbox. Unconfigured and unrelated ordinary tasks do not fill
the queue. Historical recovery is scoped to that same source.

A fresh claim requires full ordinary admission: open admissions, stores,
revocation readiness and required ports. The actor rechecks before new stages
and checkpoints. The durable row decides first submit versus readback; its
atomic claim also handles concurrent consumers. ACK requires a completed,
currently authenticated snapshot, including distinct NextUse for NoUpdate.
Successful required services remain alive until daemon cancellation.

## Recovery boundaries

- Root FileCas stays at Root. The adapter cannot register an owner, issue
  evidence, reopen a Root pathname or substitute storage.
- A blocking CAS lane stays occupied after waiter cancellation until I/O ends.
  UDS uncertainty consumes its connection; the original launcher must provide
  any fresh connection used to reconcile the same operation.
- Descriptor and outbox data confer no stage, selection, signing or effect rights.
- Claim-before-checkpoint crashes, queue-full after claim, and incomplete
  checkpoints remain pending/readback-only. Absence does not prove no work ran.
  There is no automatic resubmission, new operation ID or deadline renewal.
- A read failure before any claim does not invent a permanent claim. A retained
  claim always prevents another submit.
- Invalid scope/evidence, missing mandatory owners or refused expired new work
  fail this configured required service. Unknown commits remain pending.
- The host remains responsible for remote job cancellation and reconciliation;
  dropping a future does not prove remote work stopped.
- The outbox retains 256 identities including ACKs. This profile selects only
  one source and polls once per second between attempts. Repeated campaigns
  still need an explicit safe retirement/rotation policy.

## Remaining acceptance gates

| Gate | Boundary |
| --- | --- |
| Checkpoint composition | Actual UDS/FileCas test fixtures do not establish production Root custody |
| Automatic delivery | One registered request; full source request must already bind the completed task receipt |
| CLI bootstrap | Real launcher, Circuit providers, stage owners and Root lane are not built by `main` |
| Training/evaluation | Real data withdrawal, bounded jobs, independent evaluation, proposal and attestations remain mandatory host duties |
| Model adoption | Original CURRENT and guarded journal are required; no conversion of Unpublished to fabricated publication |
| Continuous learning | Arbitrary request creation, multi-operation registration and safe continuation remain open |
| Production acceptance | HOLD; no deployment, adoption or independent learning-gain claim |

Exact tested source identities, commands, outcomes, ignored/unselected cases and
post-test maintenance are recorded with publication. Composition tests do not
establish learning efficacy, independent evaluator custody or a general LLM ABI.
Q24 keeps its stateless, Reset-only, one-forward-per-task scope.
