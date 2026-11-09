# Fixed graph Cell architecture — accepted decisions

Decision date: 2026-11-09. Status: **accepted architecture; implementation and
qualification remain individually evidenced**. This record implements the
user's eight decisions. It does not confer production or research admission.

## 1. Cell is an inheritable stateful computation and learning unit

The stable boundary is an identity, an immutable implementation and parameter
binding, an explicit state schema and semantics, bounded inputs/outputs, an
execution budget, and the original owner of state and committed effects.
Inheritance transfers a validated state/version relationship. It never copies
another principal's authority or treats an unverified checkpoint as valid state.

Backend choice is separate from this boundary. A backend supplies its own
validated state transition and compatibility rules. The existing native
`CellDefinitionV1` and `SparseCheckpoint` still contain Sparse-specific state;
they are a compatibility implementation, not proof of a universal state ABI.
The Q24 composition remains stateless and Reset-only. An arbitrary HCSN, GRU,
SSM or transformer state must not be relabelled as a Sparse checkpoint. A new
backend needs explicit admission, state validation and versioned recovery.

## 2. Keep two trainable implementation routes

Route A uses a shared frozen semantic foundation and private Cell heads or
adapters. Share only a verified compatible base/model, encoder/tokenizer,
numeric profile and domain binding. Keep per-Cell parameters, state, requests,
scope, receipts and commits separately owned. Updating a private head does not
authorize changing the shared foundation or encoder.

Route B uses a small stateful temporal kernel. The existing GRU and diagonal
recurrence are controls; the diagonal recurrence is not a claim of implementing
Mamba or S4D. Preserve parameter and optimizer identities and reset hidden state
when the declared compatibility contract requires it.

The common candidate retains `scripts/hepta_cells` and the native local-update
contract from `4cc753af511bf7c406608caa9da0795d7691bd23`. Its experimental Python
SQLite owner remains distinct from the native daemon owner. NumPy gradients
and the optional MLX serving probe do not establish ordinary daemon activation
or an unseen-task benefit.

The new `CircuitCellRegistryV1::new_with_bundle_manifest` permits independent
complete Cell bundles in one fixed graph. The canonical manifest pins each
unique Cell's bundle and complete semantic definition. Route policy separately
pins graph positions and candidates. The original `new` constructor keeps its
uniform-bundle contract. This composition does not itself prove a common model
allocation or change the existing inference batching policy.

## 3. Preserve deterministic responsibilities

Identity, generation fences, authorization, journals, replay, artifact hashes,
quota enforcement, exact retrieval and finite rules retain deterministic
implementations where these meet the task. A learned prediction can propose an
action; it does not replace the owner that validates or commits that action.

## 4. Start with seven functional lineages

The initial experimental roles are perception/encoding, memory/association,
prediction/simulation, decision/coordination, verification/risk, tool/action,
and evaluation/adoption. These are responsibilities, not seven mandatory
model classes or a fixed number of instances. A deterministic implementation,
a shared provider or several specialized instances may serve a role. Changes
to the type/instance count need measured task and resource evidence.

## 5. Keep HCSN and NDU replaceable

Mathematical validity, trainability, and end-task benefit are separate claims.
Each needs its own evidence. HCSN must be compared with admitted temporal
controls; NDU must be compared with deterministic, fixed-budget and learned
controller controls. Neither is an obligatory bottleneck in ordinary execution.
No new HCSN admission or NDU efficacy claim follows from this composition.

## 6. Keep the original execution and recovery skeleton

App Server, the original owner, journal, artifact, generation and tool execution
boundaries stay authoritative. A completed Circuit creates a durable pointer,
not a new training, signing or selection capability. A claimed operation with
missing or uncertain recovery remains the same operation and is readback-only.
NoUpdate still requires an independently identified successor to consume the
retained model before the full iteration is acknowledged.

The common candidate accounts for the original learning channel's queued or
active commands and the outbox's unacknowledged claims during both ordinary
shutdown and Supervisor drain. A lost caller ACK does not release active work.
An unacknowledged claim may mean an uncertain commit or a pending successor;
the drain report must not call it proof that training is currently running.
Dropping an async future is not evidence that an external job stopped.

Scope V2 remains bound through original registered checkpoint composition and
readback. The legacy Root V1 wire carries no V2 frozen-scope commitment and
therefore refuses a scoped owner rather than silently dropping that binding.

## 7. Integrate ordinary entry, representations, serving and learning ownership

The source composition preserves four published candidate lines:

| Source | Exact commit | Contribution |
| --- | --- | --- |
| M6 | `885dae0f3285267e9e9c49d8b43b0d009779f9e8` | Ordinary Circuit entry, durable completion, recovery and native gates |
| Representation and ordinary learning | `5530f84e1305c4c86b8be19c4c8765c4340e51db` | Representation ports, Q24 composition, original checkpoint adapter and supervised delivery |
| Two producer routes | `4cc753af511bf7c406608caa9da0795d7691bd23` | Shared semantic/private-head and small temporal implementations |
| Scoped real learning | `342fb02346fb1a2f97d684fb1a3ef9042737401b` | Frozen learning scope, protected recovery and real-model test entry points |

This is one source candidate with explicit ancestry, not a claim that separate
passing runs tested their combined behavior. Candidate-specific results belong
in `VALIDATION.json` and its original logs.

The supervised ordinary consumer currently accepts one explicitly prebound
request and its exact completed source receipt. The default CLI still needs
actual Circuit providers, stage owners and production configuration. Continuous
request registration, safe outbox retirement and repeated campaigns remain
additional integration work. The parallel Root profile stack ending at
`b443fe0cd7642316d016d78d6d3fbaa3e9dfc341` was observed but is not included in
this candidate. It must be integrated and revalidated before claiming its
capabilities here.

## 8. Prove fixed-graph first-order benefit before organizational evolution

The next research outcome is a fixed graph with a shared foundation that learns
from ordinary task results, selects a verified candidate or NoUpdate, and
improves independently held unseen successor tasks under the complete budget.
Do not use parameter changes, successful adoption, retained state, or a
synthetic correctness score as substitutes for that outcome.

### Frozen experiment and original evidence

Before accessing confirmation outcomes, freeze the graph, foundation, allowed
update scope, source/model/data identities, training and selection protocol,
budget, evaluator, thresholds, task families and all comparison arms. Record
every admitted attempt, including failures, cancellations, uncertain outcomes,
retries and resets. A retry or replay is not a new independent sample.

Use the existing joint configuration and research foundation interfaces. The
new foundation V3 reads a hash-bound typed source registry: task identity,
complete task SHA256 and lineage group for training, tuning, selection and one
declared successor. It rejects identical task bytes under aliases, conflicting
IDs and cross-partition lineage reuse. V1 and V2 retain their old semantics.
Consistent declarations still leave actual custody, hidden exposures, evaluator
authenticity and original successor execution unverified.

The actual consumption evidence must come from the original ordinary execution
owner and bind the selected bundle/model, backend, encoder, state schema and a
different task. The source task result must precede learning and selection;
successor outcomes must not influence either. Cold recovery must explain the
same selection and consumption without duplicate work or fabricated receipts.

### Comparisons and complete cost

Use a frozen shared foundation with a retained private head, the learned private
head, and the relevant deterministic/retrieval/temporal controls. Match the
declared budget and initial conditions. Evaluate both new-task utility and
retention, with independent repeated fits and task-family separation. Report
the paired outcomes, uncertainty and every failed fit, not just successful
training or selected seeds.

Meter setup/model loading, task input/encoding, serving, retrieval, planning,
verification, data preparation, training, tuning, evaluation, signing,
publication/adoption, communication, state I/O, recovery, failures and successor
execution. Account shared allocations once while preserving each private
allocation and attempted execution. Keep wall time, CPU/GPU work, memory and
energy in their own units. Unmeasured quantities remain unknown, never zero;
excluded windows or unreconciled attempts prevent a complete-budget claim.

`LearningIterationBudgetV1` currently limits training/data/artifact work. It is
not the complete experimental cost ledger. The current research gate's
descriptive comparisons and typed source registry cannot authenticate that
ledger or independently seal a confirmation set.

### Required outcomes

Engineering closure requires real ordinary entry, original task completion,
actual bounded learning or NoUpdate, original selection/publication,
independently identified successor consumption and recoverable end state.
Scientific closure additionally requires a verified unseen task set, complete
budget and positive paired end-task evidence against the frozen controls.
If no candidate clears the declared threshold, retain NoUpdate and the failure
evidence. Organization mutation and recursive improvement stay gated behind
this fixed-graph result.

The earlier real-model Adopt run remains a counterexample: the candidate's
limited evaluation improved from 1/4 to 2/4 by answering `no` on every question,
and it still answered the distinct comparison successor incorrectly. Its
`HOLD_NO_GO`, exposed outcomes and absent independent evaluation are preserved;
this source integration does not upgrade that result.
