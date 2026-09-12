# Hepta Global Modular Development Plan

**Plan ID:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN`
**Version:** `8.0.0`
**Date:** 2026-09-01
**Status:** canonical policy and static registries are defined by this document set; live branch, pull-request, CI, selection and default-branch facts are resolved only from current exact-candidate receipts and are never cached here.

This is the only global human-readable development authority in the working tree. Machine registries own bounded facts and `docs/STATUS.md` is generated. This document grants no runtime, model, provider, tool, network, filesystem, secret, Matrix, fleet, operator, promotion, or release authority.

## 1. Mission and truthful completion model

Hepta shall become a modular, local-first agent system that can be developed by dozens of people or agents without sacrificing hot-path performance, safety, data ownership, recoverability, or whole-system optimization. The V8 architecture adds a governed longitudinal-intelligence layer while preserving the V6 execution and authority foundations.

The target system combines:

```text
immutable authority, truth, privacy and durability kernel
+ request-bound Objective Compiler
+ hierarchical NDU preference–utility spine
+ local Neuron and calibrated Intuition substrate
+ Prompt Intervention factor pricing, portfolio and timing
+ Hölder-regular Bellman/operator learning
+ causal longitudinal learning ledger
+ next-snapshot artifact and plasticity governance
```

“Global optimum” means only the best feasible plan for an exact state snapshot, objective revision, preference-state revision, hard-constraint set, candidate set, horizon, solver and time budget. Exact optimality, a bound, or a disclosed heuristic limitation must be recorded. Hepta must never claim universal or permanent global optimality.

Completion requires one integrated source tree, current exact-candidate evidence for every applicable package, independent decisions in their designated lanes, and separate promotion/release. Normal merge commits preserve reviewed branch history; linear ancestry is not a capability requirement. Until the corresponding executable and empirical conditions hold, `all_gaps_closed=false`, `closedLoopLearning=false`, `longitudinalEfficacy=false`, `functionalBiomimicry=false`, and `selfIteration=false`.

Ordinary development follows the repository owner's authorized scope. A reviewed
PR may integrate multiple lanes through small ordered commits, with one owner for
each changed durable domain. Git records source/tree/parents, CI derives the
candidate identity from the actual event, and the PR records changes, tests and
remaining work. Do not require a separately handwritten receipt, expiring lane
envelope, production host binding or deployment approval merely to implement,
test or merge authorized repository changes. Those records apply when their
runtime, independent-evaluation or deployment boundary is actually exercised.
Repository merge does not itself activate that boundary.

## 2. Canonical document system and historical cleanup

Read in this order:

1. `docs/CURRENT.json` — static source-selection policy and explicit prohibition on cached dynamic candidate facts;
2. this document — global requirements and delivery policy;
3. `docs/architecture/ARCHITECTURE.json` — non-negotiable architecture invariants;
4. `docs/modules/MODULES.json`, `docs/contracts/*` and `docs/data/DATA_AUTHORITY.json`;
5. `docs/delivery/WORK_PACKAGES.json`, `PATH_OWNERSHIP.json` and the three DAGs;
6. `docs/control-plane/OBJECTIVES.json`, `NDU.json` and `OPTIMIZATION.json`;
7. `docs/intelligence/PROMPT_INTERVENTIONS.json`, `docs/learning/ALGORITHM_SPECS.json`, `PAPER_TRACEABILITY.json` and the six implementation-level adaptive specifications;
8. `docs/readiness/README.md`, `READINESS.json`, `PROTOCOLS.json`, `GAPS.json` and the nine pre-coding execution specifications;
9. `docs/cns/README.md`, `CNS_ARCHITECTURE.json`, `ORGAN_PROTOCOLS.json` and the deterministic CNS reference;
10. `docs/hnmf/README.md`, `HNMF.json`, `TECHNICAL.md` and the three HNMF qualification references;
11. `docs/learning/LEARNING_SYSTEM.json`, `EXPERIMENTS.json`, `ARTIFACTS.json` and the generated `ALGORITHM_STATUS.md`;
12. `docs/evidence/CLAIMS.json`, `QUALIFICATION.json`, `INDEX.json` and exact external receipts;
13. `docs/security/THREAT_MODEL.json` and independently issued decisions.

Stable paths are updated in place. Version numbers live inside documents, never in filenames. Historical plans, status snapshots, current-plan pointers, gap ledgers, tranche narratives, Dropbox exports and in-tree archives are prohibited. Git history and immutable content-addressed external evidence preserve provenance.

The pre-selection baseline contained 143 historical development paths. V8 deleted that complete set in the same commit that installed the canonical document system. Git ancestry now preserves every pre-consolidation branch tip without overlaying an obsolete branch tree or reintroducing an in-tree historical plan. Code-consumed APIs, schemas, policies, migrations, tests and implementation contracts remain protected.

`python3 scripts/hepta-docs.py verify` runs on every pull request and default-branch push with read-only permissions and no path bypass.

## 3. Current truthful baseline

No branch name, pull-request number, queued workflow, cached check result or prose claim is source-selection authority. `docs/CURRENT.json` records only the static repository identity, cleanup baseline, claim levels and dynamic-observation policy. The current source head, source tree, target branch, merge candidate, CI, review and operator decisions must be resolved from a fresh `CanonicalSourceReceiptV1` or the exact external receipt defined by the global verifier.

The static repository policy records `main` as the observed administrative default at the V8 cleanup baseline. `DOC-2-DEFAULT-BRANCH-SELECTION` remains `blocked_external` until a current repository-administration observation proves a different state. The document tree must not infer that `main`, the recorded default, or any candidate branch is selected merely because equivalent bytes exist or a pull request is open.

Historical cleanup remains bound to the exact head/tree and 143-path deletion inventory in `DOCUMENT_SYSTEM.json`. Live branch counts, pull-request counts and branch-tip relationships are deliberately excluded from canonical files because they can change after a commit. This posture grants no runtime, model, provider, tool, network, filesystem, secret, Matrix, fleet, operator, acceptance, selection, promotion or release authority.

## 4. Immutable execution, authority and data invariants

- Codex App Server remains the sole session, thread, turn, model-call and tool-execution spine.
- Agentd is a thin composition/lifecycle host and owns no product-domain durable fact.
- Every durable fact has exactly one schema owner and one authoritative writer.
- A module never directly mutates another owner’s store.
- Cross-owner mutation is local transaction → durable intent → outbox → destination dedupe/apply → acknowledgement → reconciliation.
- Queue or dispatch acknowledgement is not terminal external-effect success.
- `Indeterminate` remains open until a current-fence reconciler records applied, not applied or quarantined.
- Every irreversible boundary consumes a short-lived, final-payload-bound, operation-bound and revocation-bound `VerifiedUseToken<C>` immediately before adapter entry.
- The adapter cannot mint the token it consumes.
- Hard objectives, authority, privacy, truth, deletion and writer ownership never become learnable parameters.
- Current-run objectives and learning artifacts are immutable. Learning generates only next-snapshot candidates.
- Central optimizers, NDU runtimes, prompt optimizers and learning modules select or propose; they do not execute effects or issue capabilities.

## 5. Forty-module architecture and team model

`MODULES.json` is authoritative for 40 modules. The V6 foundation remains and the Intelligence responsibilities are decomposed into bounded teams:

```text
objective.compiler
utility.ndu
neuron.runtime
intuition.policy
prompt.registry
prompt.optimizer
context.compiler
learning.ledger
learning.operator
learning.eval
learning.artifacts
learning.plasticity
intelligence.control  # composition façade only
```

`trajectory.store` is replaced by the more complete append-only `learning.ledger`. `learning.shadow` becomes the narrower `learning.eval`. The former broad `intelligence.control` no longer owns learning facts, prompt facts, artifacts or model execution.

Each module has a primary owner, deputy, exclusive roots, dependencies, data authority, forbidden authority and bounded work packages. One developer or agent receives a work envelope, not broad repository ownership. Cross-module changes require explicit co-ownership or a separate integration package.

## 5A. Closed-world module implementation guides

Every one of the forty registered modules has one stable implementation guide at `docs/modules/<module-id>/TECHNICAL.md`. `docs/modules/MODULE_DOCS.json` binds each guide to its exact digest, contracts, protocols, data domains, threats and work packages. `docs/modules/SOURCE_BINDINGS.json` separates declared target roots from existing implementation evidence, missing roots and the bootstrap package that must materialize each target.

Source states are deliberately truthful: a module may be `existing_bound`, `existing_legacy_aggregate`, `existing_declared_unbound`, `target_partially_materialized`, `target_unmaterialized` or `external_with_adapter_target`. Documentation readiness never changes a source, activation, acceptance, promotion or release claim. `python3 scripts/hepta-module-docs.py verify` fails unless all forty guides, bindings and registry references are closed.

The module registries expose two separate boolean facts for every module: `source_root_present` records only that a declared source root exists in the exact candidate tree, while `production_implementation` is true only after a named product caller and executable product tests are evidenced. A present source root therefore cannot be read as a production implementation. The two facts are projected identically through `MODULES.json`, `SOURCE_BINDINGS.json` and `MODULE_DOCS.json` and are validated against `docs/readiness/STATUS_MODEL.json`.

## 5B. Adaptive algorithm closed world

The implementation-level adaptive document set is globally governed, not an independent prose island. `docs/learning/ALGORITHM_SPECS.json` binds the six specifications, exact Git blob identities, paper claim anchors, canonical contracts and protocol schemas, data-authority domains, quantitative experiments, artifact lifecycle, work package `DOC-3D-ADAPTIVE-ALGORITHM-DOC-CLOSED-WORLD`, and both read-only CI workflows.

`python3 scripts/hepta-algorithm-docs.py verify` is necessary but cannot self-certify closure. `python3 scripts/hepta-docs.py verify` must load the algorithm registry, invoke the dedicated verifier, confirm every adaptive path is in `DOCUMENT_SYSTEM.json`, and confirm the package and Development/Activation/Evidence DAG edges. Both exact source and deterministic synthetic merge candidates must pass. Temporary installers, split payloads, `contents: write`, branch pushes, and workflow-generated source mutations are forbidden in the final document tree.

## 5C. Pre-coding implementation-readiness closed world

`docs/readiness/READINESS.json` binds nine implementation-level execution specifications, 31 bounded typed protocols, 54 closed documentation gaps, all 40 modules, seven primary implementation lanes, three cross-lane integration tracks and nine explicitly authorized external-system assimilation components. `docs/readiness/GAPS.json` separately names nine capability or evidence gates that repository documentation may never self-certify.

Every module guide includes Section 16 and maps the module to exactly one primary lane, the applicable readiness specifications, its owned and consumed readiness protocols and a common coding-entry gate. The gate requires a current exact source receipt, frozen contract/readiness digests, an existing bounded work-package envelope, deterministic fallback, declared fixtures, rollback and zero authority delta. The new embodiment and assimilation work packages define source paths and predecessors without claiming that those paths are materialized.

`python3 scripts/hepta-readiness.py verify` checks document depth, protocol bounds and ownership, gap traceability, module/lane closure, package references, assimilation target-root ownership, generated status and the read-only source-head/synthetic-merge workflow. The global verifier invokes the readiness, CNS and HNMF verifiers; no subordinate layer may certify itself as globally complete. Documentation closure permits contract-first coding to begin through the declared lanes, but it does not imply source implementation, real model use, future-time efficacy, biomimicry, physical safety, external-system owner consent, operator acceptance, selection, promotion or release.

## 6. Objective compilation

Each request is compiled into `ObjectiveFunctionV1` before adaptive logic runs. The receipt binds:

```text
request and principal scope
success predicates and terminal conditions
hard constraints and evidence requirements
allowed and forbidden action classes
soft utility dimensions
resource endowment and deadline
risk class and rollback requirements
objective revision and digest
```

The immutable core cannot change during a run. A change in user goal, success predicate, authority, privacy, allowed effects or acceptance criteria creates a new objective revision and a new run snapshot.

Soft preference dimensions may adapt only within registered bounds. A system may change how it allocates time, tokens, evidence effort, exploration or abstention while pursuing the goal; it may not replace the goal with an easier one.

## 7. Correct use of Neural Differential Utility

NDU is not a universal name for any forward/backward software module. Its forward component is the resource-constrained subject’s endogenous preference state; its backward component is recursive utility or a utility aggregator. Neural parameterization expresses preference dynamics or utility aggregation.

Only four subject levels are permitted:

```text
System NDU
Domain NDU
Agent NDU
Episode NDU
```

A database row, TaskFlow node, adapter, authority kernel or individual Hepta neuron is not an NDU subject.

The engineering discretization is:

```text
preference state P(k)
+ observation, resource consumption and outcome
→ next preference-state candidate P(k+1)

instant utility + preference state + continuation utility
→ recursive utility U(k)
```

Parent and child NDU subjects communicate bounded boundary conditions, resource/risk budgets, shadow prices, continuation utility, uncertainty and residuals. They never exchange credentials, capabilities, unrestricted hidden states, unrestricted prompts or unbounded gradients.

System and domain NDU snapshots are slow, local-cacheable control inputs; they must not create synchronous central RPC on local hot paths. Multi-level updates are damped and staged so parent and child policies do not chase one another without a frozen reference.

## 8. Neuron and Intuition

A Hepta Neuron is the local temporal/adaptive substrate that implements or estimates preference-state dynamics and fast signals; it is not itself an NDU. The target mechanism contains:

```text
shared frozen local encoder/backbone
small task head or adapter
bounded recurrent state
sparse activation and lateral inhibition
adaptive threshold and homeostasis
bounded eligibility trace
prediction error and OOD/abstention
model, device and resource receipts
```

A local model adapter, Ollama/LM Studio endpoint or checked model ID does not prove H5/Neuron use. A valid N1 claim requires exact weights, tokenizer, preprocessor, quantization, license/SBOM, runtime, device, resource and real consumer evidence.

Hepta Intuition is a calibrated fast policy. It consumes the frozen objective, NDU preference/utility state, Neuron signals, protected Memory/KG evidence, Prompt portfolio, complete legal action set and risk/resource state. It emits an action distribution, propensity, selected action, value/confidence, OOD, abstain/ask or slow-path request. It cannot write Memory/KG, call tools/providers directly, override a hard veto or treat model prose as authority.

Low-risk, read-only, reversible and supported decisions may use the fast path. High risk, OOD, insufficient support or low confidence must use the governed slow path and deterministic validation.

## 9. Prompt Intervention Market

The normal mechanism is called **Prompt Intervention** or **Context Intervention**. “Prompt injection” is reserved for the security attack.

A semantic `PromptFactor` is separated from model-specific `PromptRealization` text or structured payload. The source of truth is `prompt.registry`; `knowledge.graph` maintains a rebuildable interaction and applicability projection; `learning.ledger` stores causal exposure/outcome facts; `prompt.optimizer` is read-only.

Prompt factors include objective anchoring, inspect-before-mutate, evidence/freshness/contradiction checks, citation, minimal diff, failure diagnosis, alternative hypotheses, verification, abstention and output schema. Every realization binds model/version, tokenizer, system template, tool schema, locale, message role, payload digest, token cost, context profile and expiry.

External webpages, documents, emails, user content and tool output are evidence channels. They cannot become trusted instruction factors without a governed transformation and registry admission.

A prompt factor is a control asset: it consumes scarce context and changes the model action distribution. Its value is the state-dependent causal increment in recursive utility minus token, latency, crowding, interference, conflict, privacy and instability cost. Hard constraints are not tradable.

The optimizer selects a bounded portfolio, not a single text. It models complements, substitutes, conflicts, prerequisites, dominance, redundancy and supersession. Timing is a discrete real-option decision over registered boundaries such as before planning, after candidate generation, after failure, before an irreversible action, before verification and before final response. Mid-generation context mutation is forbidden unless separately specified and qualified.

## 10. Hölder-regular Bellman/operator learning

The V8 slow learner does not convert the whole system into DQN. It learns bounded continuation-value and Bellman operators for selected smooth state subspaces.

State is partitioned into:

```text
smooth continuous axes
+ discrete event/jump axes
+ deterministic authority/truth axes
```

Authority, lease, CAS, truth and writer-ownership axes are never noised or learned.

Operator learning uses a fixed, versioned `OperatorSensorCore` that is separate from the causal replay ledger. Runtime experience may not silently replace the sensor core. Coverage, fill distance, separation radius, mesh ratio, OOD margin, effective rank and resource budget are measured.

The target architecture separates continuation-value branch encoding, smooth state trunk and Lipschitz/categorical action trunk. Low separation rank is an empirical requirement, not an assumption disguised as evidence. Reconstruction must be bounded, monotone/positive where required and approximately non-expansive in the declared norm. Residual Bellman mode is permitted only for a measured near-greedy active set; off-policy candidates use a direct target or action-gap head.

Control steps are chosen at meaningful event/episode boundaries. The system does not run a full Bellman solver at every token or micro-event.

## 11. Causal learning ledger

`learning.ledger` is the append-only source for:

```text
RunStartSnapshot
LearningEpisode and ordered events
complete action and prompt candidate sets
selection propensities and support
model/tool/prompt decisions
observed outcomes and delayed watermarks
corrections, forgets and revocations
credit entries and conservation
artifact/dataset lineage and unlearning
```

The observing store or adapter, not the policy being evaluated, records effect and outcome facts. A policy cannot label its own action successful. Memory persistence is not long-term learning.

The first closed loop must include no-intervention baselines, single-factor and pairwise ablations, timing ablations, model-version isolation, support-aware OPE and future-time validation.

## 12. Fast runtime loop and slow learning loop

Fast loop:

```text
ObjectiveSnapshot
→ NDU state
→ Neuron signals
→ Prompt portfolio and exercise decision
→ Intuition action distribution
→ bounded ContextCompilationReceipt
→ Codex/TaskFlow authorized action
→ observed outcome
→ immutable learning event append
```

Slow loop:

```text
causal segmentation
→ support and propensity audit
→ credit assignment
→ operator/policy/head/prompt training
→ replay and off-policy evaluation
→ safety/subgroup/privacy/resource tests
→ future-time and retention tests
→ signed next-snapshot artifact
→ shadow
→ bounded canary
→ independent operator acceptance
→ separately governed selection/promotion/release
```

No slow-loop component mutates the current run or constructs the production writer.

## 13. Artifact lifecycle and rollback

`learning.artifacts` is the create-only source for model, adapter, policy, Bellman operator, prompt policy, NDU parameter and sensor-core artifacts. Every artifact binds source dataset, code, model/runtime, objective class, compatibility, resource envelope, expiry and rollback predecessor.

Lifecycle states are proposed, trained, evaluated, shadow, canary, operator-accepted, selected, revoked and retired. Bytes never change in place. Reload and rollback are tested across process kill, acknowledgement loss, stale generation, database reopen and restore.

A generated artifact is not selected; selection is not operator acceptance; acceptance is not promotion; promotion is not release.

## 14. Longitudinal learning

Long-term learning is claimed only after the selected artifact changes future behavior and produces bounded improvement on future time windows while respecting old-task retention, OOD, subgroup, privacy, resource, correction, deletion and rollback requirements.

Required evidence includes:

- complete candidates and logged propensities;
- ESS, IPS, SNIPS, doubly robust estimates and confidence intervals;
- candidate LCB greater than baseline UCB;
- delayed outcomes and distribution shift;
- old-task holdout and forgetting bounds;
- multiple snapshot iterations;
- deletion/unlearning non-resurrection through caches, indexes, replay, artifacts and backup/restore.

## 15. Functional biomimicry

NDU provides dynamic preference and recursive-utility semantics; it does not itself prove biological mechanism. DeepONet/Bellman operators provide a slow value learner; they do not themselves provide local biological plasticity.

A functional-biomimicry claim additionally requires temporal state, sparse competition, lateral inhibition, bounded eligibility traces, homeostasis/metaplasticity, neuromodulatory signals, replay consolidation, prediction error, and lesion/ablation evidence. The local update may use a bounded three-factor form based on local eligibility and a low-dimensional modulator, but production changes remain next-snapshot only.

A neuromorphic claim is a separate research level requiring spike/event-native execution, local timing plasticity, asynchronous sparse computation, exact hardware/simulation identity and fair energy/latency baselines.

## 16. Governed self-iteration and plasticity

Allowed self-iteration outputs are parameter, artifact, PromptFactor, topology, workflow, skill and code candidates, together with tests, evidence and rollback plans.

Structural operations include add, split, merge, retire and rewire. They run only through:

```text
proposal
→ capability typing and sandbox
→ security/resource review
→ causal evaluation
→ lesion/ablation
→ signed topology snapshot
→ shadow and bounded canary
→ independent acceptance
→ rollback-capable selection
```

Hepta may self-generate, self-test, self-evaluate, self-diagnose and self-propose. It may not self-authorize, self-review, self-select, self-merge, self-accept, self-promote or self-release.

## 17. Runtime and Engineering Control Planes

The Runtime Control Plane consumes exact global state, readiness, resources, module Pareto candidates, NDU summaries, policies, deadlines and fences. It emits a selected feasible plan, resource allocation, fallback and decision receipt, then requests separately governed execution grants. It remains off the local hot path unless bounded use is explicitly qualified.

The Engineering Control Plane consumes the work-package DAG, team skills/capacity, source-root conflict graph, review topology, CI capacity, expected value, architecture debt and rollback cost. It emits bounded assignments, integration order and merge-queue proposals. It cannot self-approve or merge its own work.

## 18. Development, Activation and Evidence DAGs

The Development DAG permits contract-first parallel work. The Activation DAG is stricter and governs integration, registration, runtime attachment and authority. The Evidence DAG prevents source, tests, semantics, causality, real model use, longitudinal efficacy, biomimicry, operator acceptance, promotion and release from collapsing into one boolean.

Every package declares exact paths, predecessors, exit criteria, stop conditions and authority delta. Valid stop outcomes are `PACKAGE_CLOSED_CANDIDATE`, `BASE_DRIFT`, `BLOCKED_UPSTREAM`, `BLOCKED_EXTERNAL`, `STOP_CONDITION` and `RESUME_REQUIRED`.

## 19. Delivery roadmap

### P0 — V8 document convergence

- Materialize this complete V8 set as one commit on the observed default baseline.
- Remove at least the 139 known historical development paths and every additional forbidden legacy path.
- Run exact-head and merge-candidate document gates.
- Obtain independent review and select only V8 into the default branch.
- Restack active implementation candidates without reintroducing deleted development documents.

### P1 — authority and modular foundation

- Qualify runtime bootstrap, common VerifiedUse, provider/model/tool/network/filesystem/secret/Matrix/fleet boundaries and B4 AST/call-site proof.
- Extract cognitive types, store, read ports, retrieval, federation, Rust KG and compact engine.
- Close dependency inversion, readiness, resource and common durable fault matrices.

### P2 — longitudinal-intelligence contracts and stores

- Complete Objective, NDU, Prompt, Bellman, Neuron/Intuition and causal-learning contracts.
- Build Objective Compiler, durable learning ledger, artifact registry and PromptFactor registry.
- Implement a deterministic NDU baseline before adaptive NDU claims.

### P3 — shadow intelligence

- Build operator sensor core and Bellman shadow learner.
- Select and prove a real local model before attaching Neuron.
- Implement temporal Neuron, calibrated Intuition, prompt pricing/portfolio/timing and Context Compiler in shadow-only mode.

### P4 — first bounded closed loop

Run `C1-PROMPTED-MEMORY-RETRIEVAL-RANK` in a read-only action domain. The initial factors are exact-source, freshness, contradiction, cite-before-use and abstain-on-stale. Compare no prompt, single factor, pairs, full portfolio, fixed timing and learned timing. Prove zero Memory/KG/tool/provider effect.

### P5 — longitudinal learning

Close causal evaluation, signed next-snapshot reload/rollback, future-time holdout, retention/forgetting and unlearning non-resurrection. Only then advance from L3 to L4.

### P6 — functional biomimicry and self-iteration

Add eligibility/homeostasis, replay consolidation, world-model prediction error, parameter plasticity, PromptFactor evolution and code candidate generation. Structural topology proposals and canary are last, never prerequisites for the first learning loop.

### P7 — simulator-first embodiment

Implement `EMB-0` through `EMB-3`: shared sensor/body/reflex/actuation types, coherent body-state storage, deterministic local control, terminal effect reconciliation and independent simulator or hardware-in-loop qualification. Real physical activation remains blocked until target-host timing, emergency-stop and safety evidence exist.

### P8 — explicitly authorized external-system assimilation

Implement `ASM-0` through `ASM-4` against an owner-authorized, non-privileged Debian/POSIX fixture. Progress from read-only discovery to manifest/contract synthesis, credential-free sandboxing, reversible migration and explicit host enrollment. Cross-host or autonomous propagation is prohibited.

## 20. First vertical learning slice

`C1-PROMPTED-MEMORY-RETRIEVAL-RANK` executes:

```text
request
→ ObjectiveFunctionReceipt
→ bounded Memory/KG retrieval candidate set
→ Episode/Agent NDU state
→ PromptFactor demand and candidate set
→ state-dependent pricing and portfolio
→ discrete exercise timing
→ ContextCompilationReceipt
→ LLM retrieval-use action distribution
→ read-only report
→ OutcomeReceipt and delayed correction
→ causal attribution
→ operator/policy artifact proposal
→ next-snapshot shadow and rollback
```

Primary metrics are task success, retrieval utility, citation precision, stale rejection, contradiction detection, abstention safety, token cost, latency, context interference, factor interactions, timing uplift, calibration, OOD and cross-window retention.

## 21. Performance, fault and security contracts

Every affected path records comparable baseline and candidate throughput, p50/p95/p99 latency, CPU, resident memory, allocations, queue depth/age, SQLite busy/WAL, file descriptors/sockets, model/provider usage, token/context cost and confidence bounds.

Stateful modules cover before/after intent, commit, outbox, wakeup, claim, send, acknowledgement, source settlement, stale callback, permission loss, filesystem full, corruption, nonempty WAL, identity drift, backup/restore and process kill/reopen.

Raw prompts, credentials, secret values, private keys, unrestricted source content and raw model payloads never enter general receipts. External content remains evidence, not instruction. Forget/correct closes only after Memory, KG/index, prompt graph, compact, federation, trajectories, sensor/training caches and signed artifacts prove deletion/rebuild or revocation.

## 22. Claim ladders and prohibited substitutions

Initial truthful state:

```text
Learning = L0_STATIC
NDU = D0_SPECIFIED_ONLY
Neuron = N0_METAPHORICAL
Intuition = I0_DETERMINISTIC
Prompt Intervention = P0_STATIC_CONTEXT
Structural Plasticity = S0_FIXED
local small model used by Neuron/Intuition = false
closed-loop learning = false
longitudinal efficacy = false
functional biomimicry = false
neuromorphic mechanism = false
self-iteration/evolution = false
```

The following substitutions are invalid:

```text
memory persisted != long-term learning
model adapter exists != local model used by Neuron
local model invoked != Neuron efficacy
offline loss improved != policy improved
replay improved != closed-loop learning
prompt correlated with success != causal prompt uplift
NDU equations specified != preference/utility efficacy
sparse activation exists != functional biomimicry
topology proposal generated != structural plasticity
artifact generated != selected
operator acceptance != promotion
promotion != release
```

## 23. Immediate queue

1. Qualify `DOC-3E-PRECODING-READINESS-CLOSED-WORLD` through the dedicated and global exact-source and synthetic-merge jobs, then obtain independent semantic review.
2. Resolve the current canonical source and target branch only from fresh receipts; do not reuse a cached pull-request number or historical branch relationship.
3. Begin `LANE-A-FOUNDATION`, `LANE-C-MEMORY` and `LANE-G-ENGINEERING` contract-first packages against frozen readiness and contract digests.
4. Close AuthBus semantic review, Browser identity reconciliation, dependency inversion, runtime bootstrap, B4 call-site proof and common fault/resource gates.
5. Materialize Objective, deterministic NDU, episode ledger, artifact registry, PromptFactor registry and the first read-only vertical slice.
6. Add Bellman, Neuron, Intuition and prompt optimization only in shadow mode after immutable stores and independent evaluation exist.
7. Require future-window, retention, rollback and unlearning evidence before any longitudinal, biomimicry or structural-plasticity claim.
8. Start `EMB-0` through `EMB-3` in simulator-only mode; real sensors, actuators and hardware-in-loop acceptance remain external gates.
9. Start `ASM-0` through `ASM-4` only with explicit external-system owner consent and a non-privileged Debian/POSIX fixture; autonomous propagation remains forbidden.
10. Keep acceptance, selection, merge, promotion and release in distinct identities and receipts.

All authority flags remain false in this document set.

## 24. V8 audit closure and executable document integrity

V8 closes the remaining V8.1 review gaps rather than merely adding prose:

- every logical module has at least one bounded work package;
- cross-module contracts, critical protocol fields and durable data domains have explicit machine owners;
- the Intelligence path has one typed composition route into Agentd and the Codex execution spine;
- package write paths, foreign-namespace co-owners and overlapping-path ordering are machine checked;
- every registry has an exact 17-field all-false authority posture and a recursive shape digest;
- the cleanup base, 143-path deletion set, exact Git objects, dangling references and deleted JSON consumers are verified;
- mutable `CURRENT.json` no longer caches future/stale CI observations; dynamic facts live only in exact-candidate receipts;
- pull-request qualification executes separate source-head and synthetic-merge jobs with explicit refs and retained receipts;
- Prompt assignment, compilation, provider delivery, token position and causal effect remain separate claims;
- longitudinal claims require at least three independently identified snapshots spanning at least two calendar windows;
- current-run replacement, online topology activation, self-review, self-selection, self-merge and self-promotion remain forbidden;
- adaptive algorithms are bound to canonical protocols, data writers, exact golden vectors, paper source locks and the global document verifier;
- nine coding-level readiness specifications close objective, NDU, neuron, evaluation, self-iteration, embodiment, assimilation, source and parallel-lane ambiguities;
- 31 readiness protocols have registered module owners and consumers, bounded fields, canonical encoding and zero authority delta;
- all 40 modules are projected into exactly one acyclic primary implementation lane and every guide carries its coding-entry binding;
- embodiment and authorized Debian/POSIX assimilation have bounded source work packages, target roots, predecessors, rollback and independent evidence gates;
- the global document system invokes module, adaptive, readiness, CNS and HNMF verifiers and binds their digests into exact-candidate receipts.

The documentation gate is necessary but does not waive unrelated repository failures. A failed repository check must be attributed and closed or explicitly excluded by an independent policy authority; documentation source success cannot turn a red product matrix green.
