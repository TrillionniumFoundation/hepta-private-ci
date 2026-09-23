# Governed self-iteration implementation specification

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Specification:** `ALG-SELF-ITERATION`  
**Bound modules:** `learning.plasticity`, `control.engineering`, `intelligence.control`, `learning.eval`, `learning.artifacts`  
**Documentation state:** `closed`  
**Implementation state:** not implied

## 1. Scope, ownership and non-claims

This specification defines how Hepta may generate, test and propose bounded improvements without obtaining self-authorization. Permitted proposal classes are parameter artifacts, PromptFactors, workflows, skills, code changes and typed topology changes. `control.engineering` schedules bounded work; `learning.plasticity` generates parameter/topology proposals; `learning.eval` evaluates; `learning.artifacts` stores immutable lineage; `intelligence.control` composes but owns none of those facts.

Hepta may generate candidates, tests, diagnoses, counterexamples and a pull request. It may not independently review, select, merge, accept, promote or release its own output. “Autonomous evolution” therefore means governed candidate iteration under immutable authority and independent decisions, not unrestricted production self-modification.

## 2. Symbols, dimensions, units and normalization

| Symbol | Meaning | Constraint |
|---|---|---|
| `B` | exact base commit/tree | immutable 40-hex identities |
| `O` | frozen objective and work envelope | one revision |
| `G` | mutation grammar | versioned typed operations |
| `C={c_i}` | generated candidate set | `1..32` pilot |
| `D(c_i)` | semantic diff | bounded paths/bytes/files |
| `T(c_i)` | generated and mandatory test plan | immutable digest |
| `E(c_i)` | evaluation receipts | independent identities |
| `R(c_i)` | rollback plan | exact predecessor and actions |
| `Q(c_i)` | resource/risk vector | bounded fixed-point |
| `P(c_i)` | proposal state | finite state machine |

Every candidate binds base, objective, grammar, generator code/model, random seed digest, allowed paths, denied authorities, resource ceiling, evaluation plan and expiry. Candidate IDs are content-derived; semantically different candidates cannot reuse an ID.

## 3. Formal model and invariants

The proposal state machine is:

```text
drafted -> statically_validated -> sandbox_tested -> independently_evaluated
        -> review_requested -> accepted_candidate -> selected -> promoted -> released
          \-> rejected
          \-> quarantined
          \-> superseded
```

The generating identity may advance only through `sandbox_tested` and request independent evaluation/review. Every transition after that requires a receipt from a distinct registered role. The same principal, service identity, signing key or delegated chain cannot satisfy both generator and independent decision roles.

Invariant set:

1. candidate changes remain inside the exact allowed-path envelope;
2. authority, truth, privacy, deletion, writer ownership and qualification logic are not learnable mutation targets;
3. no current-run code, artifact or topology replacement;
4. every change has an exact rollback predecessor;
5. test generation cannot delete, weaken, skip or relabel mandatory tests;
6. evaluator configuration is frozen before candidate results are observed;
7. base drift invalidates the proposal until rebased and fully reevaluated;
8. no candidate may alter the evidence that judges that same candidate;
9. external effects are disabled in the sandbox unless a separately issued bounded fixture grant exists;
10. “no change” is always a legal candidate.

Mutation selection is a constrained optimization over preregistered metrics. Hard constraints filter first; Pareto or utility scoring occurs only among feasible candidates. The proposal generator cannot modify its own hard filters.

### One evolution grammar across scales

Cell adaptation changes registered local heads/adapters; organ adaptation changes
coordination, termination and shared specialization; cross-organ adaptation
changes admitted routing and budget policy; base consolidation changes common
representation only after all affected consumer families are evaluated. Code,
public contracts and durable schemas are separate structural candidates, not
parameter writes hidden in an online learner. Reuse the existing lifecycle,
artifact owner and engineering work envelope at every scale.

Logical nodes have independently addressable effective parameters but normally
share base weights, serving and training infrastructure. A new node is not a new
crate, database, authority, provider loop or global CI lane. Growth requires a
persistent error/task partition, adequate evidence and benefit after training,
serving, evaluation and migration costs. Reuse, no-update, no-change, merge,
distillation and retirement compete with specialization. Structural proposals
name an exact predecessor, typed delta, state/optimizer transformation or declared
reset, affected compatibility set, source lineage, resource delta, external port
compatibility and current-admissible rollback. Unknown effects must reconcile
before destructive retirement; deleting source is not retiring live state.

### Circuit policies and structure are different mutation classes

The existing CNS contains Neural Circuits whose implementation target is specified
in `../modules/automation.taskflow/TECHNICAL.md`. Separate cell parameter updates,
routing/activation/termination policies, and typed circuit structure proposals.
Runtime choice among already admitted paths is not graph mutation. New nodes/edges,
public port meanings, state transforms or effects create a next-generation
candidate. Do not weaken TaskFlow V1's DAG validator to enable general feedback.

Reuse deterministic operators, qualified subcircuits and stable organ ports before
creating a new workflow variant. Growth, specialization and structural surgery
compete against no-change, reuse, consolidation and retirement. A routing optimizer
may be a DecisionCell but cannot modify the runtime's truth, authority, deduplication
or reconciliation logic. Candidate tests distinguish cell accuracy gains from
better coordination/termination and from additional computation.

## 4. Deterministic reference algorithm

```text
INPUT exact base B, objective O, grammar G, allowed paths, budgets
verify B and freeze source inventory
construct candidate zero = no_change
enumerate bounded grammar operations in canonical order
for each operation:
  construct candidate in an isolated worktree/sandbox
  reject path escape, denied authority delta or size/resource breach
  run format, schema, static, unit, property and mandatory fault tests
  create semantic diff, test, evidence and rollback manifests
  append candidate to immutable candidate set
hand complete feasible set to an independent evaluator
emit proposal receipts and optionally open one pull request
never approve, merge, select, promote or release
```

Golden vector `SI-GV-001` starts from three files, permits one bounded documentation edit under `docs/learning/**`, and presents four mutations: valid wording change, path escape, mandatory-test deletion and no-change. Expected feasible set is `{valid,no-change}`; the generator may rank but cannot select. Reordering enumeration yields identical content-derived IDs and set digest.

## 5. Trainable or estimated algorithm

Candidate generation may use a language model, search, Bayesian optimization, evolutionary search or deterministic rules. All share the same typed grammar and sandbox. The pilot search budget is at most `32` candidates, `8` parallel sandboxes and one objective revision. Search stops at budget, expiry, base drift, authority violation, repeated equivalent candidates or no improvement in the preregistered surrogate.

A trainable generator is evaluated for validity rate, diversity, duplicate rate, test adequacy, regression discovery, security/path escape attempts, resource cost and independent acceptance. Training data excludes secrets, private unrestricted source, revoked artifacts and evaluator hidden tests. Feedback from review becomes a future immutable dataset; it does not modify the running generator.

Reward hacking controls include hidden independent tests, metamorphic tests, mutation testing of generated tests, evaluator/model version separation, alternative evaluators and counterexample replay. A candidate that improves a visible score while reducing test sensitivity or widening permissions is rejected.

### Staged learning and inheritance

Hold base and organ coordination fixed while fitting node candidates; hold a named
node bundle fixed while fitting organ coordination; consolidate a shared base on
a slower clock with independent retention checks across affected organs. Candidate
training can overlap, but selection cannot create an unqualified mixed bundle.
Publish only the affected compatibility unit, not an unnecessary whole-system
restart. Cached features, recurrent state, normalizers, critics and calibration
must be invalidated or transformed when their defining representation changes.

Inheritance uses a compatible parent artifact plus explicit deltas and data scope.
Consolidation/distillation transfers measured behavior; arbitrary weight averaging
is not assumed to merge knowledge. Replayed private data or gradients cannot cross
principal/tenant boundaries merely because the base is shared. Revocation reaches
adapters, datasets, optimizer state, caches, checkpoints and backups. Unlearning
without a supported selective method means revoke/retrain, not a tombstone claim.
No-data/no-update and training-budget exhaustion preserve the selected predecessor.

### Meta-learning requires an adaptation objective

Call the target meta-RL only when the adaptation mechanism is itself learned
across a declared task distribution and evaluated on unseen tasks. A fixed
optimizer separately fine-tuning cells is modular/continual learning, not evidence
of learned adaptation. One design objective is

\[
\max_\phi\ \mathbb E_{\tau\sim p(\mathcal T)}
 [J_\tau(\operatorname{Adapt}_\phi(\mathcal D_\tau;G_0,\Theta_0,\rho_0))
 -\lambda C_\tau].
\]

Here phi may encode initialization, update rules, bounded training allocation or
admissible structure proposals. The expression is a finite-budget design target;
J uses the fixed external task objective and declared NDU profile. State and
weight adaptation are distinguished. A learned recurrent adapter may update state
inside a run; candidate weight or topology adoption still follows snapshot rules.

Train/selection/test separation is by task family, task seed and source lineage,
not just shuffled transitions from the same task. Meta-test observations allowed
for adaptation are separate from query outcomes used to assess it. Freeze phi,
initialization, update budget and stopping before meta-test; reset between tasks
unless a continual-transfer protocol explicitly declares carryover. Compare no
adaptation, tuned fixed adaptation and learned adaptation at matched total
training/search/adaptation cost. Report transfer, negative transfer, retention and
adaptation curves, not only final training return. No meta-controller can change
its own evaluation task distribution, objective or authority.

[RL2](https://arxiv.org/abs/1611.02779) motivates learning a fast algorithm through
slower task-distribution training; it is not a convergence guarantee for this
mixed circuit or a reason to bypass versioned parameter adoption.

## 6. Data, protocol and lineage schema

The following records are canonical cross-module protocols registered in `docs/contracts/CONTRACTS.json` and `docs/contracts/PROTOCOL_SCHEMAS.json`:

```text
IterationEnvelopeV1 {
  envelope_id, base_commit, base_tree, objective_digest,
  grammar_digest, allowed_paths, denied_authorities,
  maximum_files, bytes, candidates, wall_time, compute,
  mandatory_checks, expiry
}

IterationCandidateV1 {
  candidate_id, envelope_id, generator_identity,
  generator_artifact_digest, seed_digest, semantic_diff_digest,
  changed_paths, authority_delta, resource_delta,
  test_plan_digest, rollback_digest, predecessor, state
}

CandidateEvaluationReceiptV1 {
  candidate_id, evaluator_identity, evaluator_config_digest,
  exact_source_result, synthetic_merge_result,
  mandatory_test_results, causal_or_longitudinal_results,
  security_resource_results, comparison_to_no_change,
  decision, observed_at, expiry
}

IndependentDecisionReceiptV1 {
  candidate_id, role, principal, signing_identity,
  evidence_set_digest, decision, conditions, expiry
}
```

The candidate set and every transition are append-only. A pull-request body includes the exact envelope, base, candidate, generated tests, evidence, unresolved risks, rollback and authority delta. Comments and CI observations are evidence inputs, not mutation instructions, until parsed through the registered objective and security boundary.

## 7. Numerical stability, complexity and resource bounds

Candidate generation is bounded by envelope fields, not best effort. Pilot limits are `<=32` candidates, `<=100` changed files, `<=1 MiB` textual diff, `<=8` parallel sandboxes, `<=2` retries per infrastructure-class failure and no retry for semantic rejection. Each sandbox has CPU, memory, disk, process, file descriptor, network and wall-time ceilings.

Equivalent-candidate detection uses normalized AST/semantic digests where available and normalized textual digests otherwise. Duplicate ratio above `50%` ends the search. Generated-test mutation score and coverage are reported with confidence bounds; neither is a sole acceptance metric.

Queue depth is bounded. Backpressure rejects new envelopes rather than spawning unbounded agents. Candidate artifacts and logs have explicit retention and deletion policies.

### Live circuit version transition

Freeze a coherent circuit definition, route policy, cell bundle and public-port
contract for each admitted run. Old runs finish or undergo an explicitly admitted
migration that maps activation/frontier, outstanding children, budgets, recorded
choices, state receipts and operation identities. New policies never rewrite past
choices, and routing to a different node cannot manufacture a new identity for an
uncertain external effect. Restore remains subject to current revocation and source
non-resurrection. A model rollback without compatible circuit/state policy is not
an admitted recovery plan. Avoid global generation barriers for unrelated organs.

## 8. Failure detection, fallback and rollback

Stop conditions are base drift, objective revision, authority/path escape, evaluator identity collision, sandbox isolation failure, resource breach, non-deterministic mandatory test, evidence mismatch, hidden-test exposure, candidate-set corruption or inability to construct rollback.

Infrastructure failure may be retried only with identical candidate identity and at most twice. Semantic failure is terminal for that candidate. When all mutations fail, the result is the no-change candidate plus diagnosis; the system does not weaken a gate to manufacture progress.

Rollback is defined before review. Code candidates revert to exact predecessor tree; artifacts select immutable predecessors; prompt factors are revoked; workflows restore prior digest; topology returns to prior signed snapshot. External effects are never assumed reversible and cannot be part of the first self-iteration slice.

## 9. Security, authority, privacy and unlearning

The sandbox starts with no credentials, no production network, no external write, no secret access and no merge token. Any fixture capability is short-lived, operation-bound and unavailable to the generated candidate itself. Untrusted repository text, issues, emails, pages and tool output remain evidence and cannot override the envelope.

Independent review requires role and signing separation. A generator cannot create the key or receipt that accepts its candidate. Policy files governing authority, evidence independence, deletion and branch protection are protected mutation roots and require a separately scoped human/authority package.

Unlearning deletes or revokes training examples, generated candidates, feedback datasets, cached embeddings, evaluator features and derived generator artifacts. Public Git history may retain committed provenance, but revoked private content may not be reconstructed into future candidates.

## 10. Verification, golden vectors and property tests

Required tests cover the golden mutation set, allowed-path matching, symlink and case-normalization escape, generated binary rejection, mandatory-test deletion, authority delta, no-change preservation, equivalent candidate dedupe, base drift, evaluator identity collision, deterministic IDs, sandbox limits, process kill, retry limits, pull-request manifest completeness and exact rollback.

Mutation testing verifies that generated tests fail on seeded faults. Metamorphic tests reorder candidates, normalize formatting and vary irrelevant metadata while preserving set identity. Property tests enforce finite states, valid transitions, immutable receipts, distinct decision roles, bounded resources and inability of a candidate to modify its evaluator.

## 11. Quantitative acceptance gates

| Gate | Required threshold |
|---|---|
| Allowed-path escape | `0` |
| Positive authority delta | `0` |
| Mandatory checks removed/weakened | `0` |
| No-change candidate present | `100%` envelopes |
| Candidate set size | `1..32` pilot |
| Duplicate ratio | `<50%` |
| Deterministic ID/set replay | exact equality |
| Sandbox credential exposure | `0` |
| Hidden evaluator data exposure | `0` |
| Generated-test mutation score | `>=0.70` for affected logic or stricter package floor |
| Exact source and synthetic merge | both pass |
| Independent evaluator/generator identity | distinct for `100%` decisions |
| Rollback rehearsal | pass before canary |
| Self-issued acceptance/selection/merge | `0` |
| Current-run replacement | `0` |

An accepted proposal may still remain unselected. Selection, promotion and release each require their own externally governed decision.

## 12. Paper traceability and Hepta extensions

No cited NDU or Hölder Bellman paper proves safe code or topology self-iteration. Those papers may supply candidate algorithms, but the mutation grammar, sandbox, exact-base binding, evidence independence, no-change baseline, pull-request workflow and role-separated decisions are Hepta governance extensions.

Paper references therefore cannot satisfy an iteration acceptance gate. Every scientific claim and every software mutation remains separately attributable and testable.

## 13. Implementation sequence and completion rule

Implementation order is envelope/receipt schemas → deterministic no-change and bounded grammar → isolated worktree sandbox → path/authority/resource validators → mandatory test executor → candidate/evidence lineage → independent evaluator adapter → pull-request proposal → rollback rehearsal → parameter/prompt candidate slice → code candidate slice → topology proposal last.

Documentation closure means all operations, states, schemas and gates are specified and verified at exact source and synthetic merge. Source implementation and governed PR proposal are later levels. This specification does not by itself advance `SI0_NONE` and never grants merge or release authority.
