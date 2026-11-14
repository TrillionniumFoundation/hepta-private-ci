# MEM-3 frozen interference and composition mechanism pilot

Status at registration: **FIXTURE_LOCKED; FORMAL_EXECUTION_PENDING**. Formal
execution waits for the first candidate-retention experiment to complete.
Scientific qualification stays HOLD; model/product adoption stays NoUpdate.

## Fixed question and information boundary

Sixteen primitive records define two functional relations A/B on eight objects.
Values and fixed 16-dimensional features come from the original MEM-1
`Owner(seed)`, using A:0..7 and B:0..7. All arms receive the same current records,
metadata, features and task program. Composite terminal answers are never
training labels. The evaluator computes them after the actor supplies a result.

Three arms share the same explicit bounded relation composer:

1. Exact-key retrieval of current evidence, followed by relation composition.
2. BM25 over the same records, with complete ranking and parsed-key validation,
   followed by the same composition. This is a strong small-corpus lexical
   baseline, not an LLM RAG or semantic-search benchmark.
3. The real Rust fast associative matrix predicts each next object from the
   current primitive key. The next hop uses its own prediction. Exact/BM25
   answers and evaluator values are unavailable to this read path.

The common owner gate receives metadata **without the value field**. It checks
source/version, revocation, expiry, dependency eligibility and task constraints.
It can abstain; it cannot replace a neural prediction with the current answer.
Raw prediction error, gate abstention, joint terminal answer and wrong assertions
are reported separately. The composer itself supplies the combination rule to
all arms. Success would not show that the neural matrix learned a novel
relational operator or has unique compositional ability.

## Frozen roster and transitions

Exactly five seeds, 0..4; four ordered fact stages; three arms: **60 planned
trials**, each with the same 64 task IDs, totaling **3,840 terminal attempts**.
Families cover unseen two/three-relation compositions, budgets/allowed endpoints,
exact version requirements, revocation, dependency invalidation, expiry and
unknown node/relation inputs. Failures, unknown outcomes and abstentions stay in
the denominator.

Stages: initial facts; A:0/A:1 version replacement; A:2 revocation plus dependent
B:3 invalidation; B:7 expiry. No actor reads future updates. Complete fixture
bytes and their hash are frozen before formal execution. No outcome-based tuning,
optional seeds or selective task removal is allowed.

## Native scope, continuous-memory limitation and costs

The unchanged MEM-1 reference driver has fixed descriptor tags and predictions
have no fact/adoption authority. MEM-3 externally binds actual feature, fixture
and program bytes and uses distinct cell IDs. This is numerical execution under
a synthetic owner, not new production encoder/owner identity qualification.

At each new owner cut, native state is rebuilt from current eligible primitives
with eight shuffled passes. All replay work is charged. This tests interference
within the rebuild and downstream composition. **It does not answer continuous
cross-version interference or establish unlearning.** The current native state
binds the complete owner snapshot; its API has no weight-preserving transition
to a new cut. Keeping the old generation number would not constitute a qualified
current-owner continuous arm.

Ten preregistered transition diagnostics (predict/update at the next cut, on each
of five base states) check this actual limitation. Rejection must leave the
checkpoint unchanged. Unexpected acceptance is retained as a failure, not used
to create a purported continuous-memory result. A future continuous comparison
needs a legitimate state-transition contract and new qualification.

Report provided serialized information bytes, stored state/metadata bytes,
retrieval candidates/payload bytes, native updates/predictions/IPC work and wall
time. Teacher calls/bytes/work are zero. Retrieval does not receive unnecessary
native-style rehearsal to inflate its cost. Shared ceilings are not equal
measured work; serialized sizes are not RSS; fixed-order timing is descriptive.

Primary outcome is joint correct terminal answer, with an additional denominator
for answerable tasks. Also report raw valid-source errors, false terminal
assertions, gate/unknown abstentions and actual invalid/revoked-source uses.
Zero invalid use caused by the shared gate is not learned neural authority.
Five synthetic seeds are not independent pretrained-model training repeats.

Keep strong retrieval in the critical path unless native association establishes
a useful full-cost benefit. Independent real tasks, richer relations, external
owner authority, representation learning and practical confirmation remain gates.
