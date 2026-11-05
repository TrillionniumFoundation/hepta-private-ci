# Native weight-space programming: mathematical scope and acceptance

This document separates implemented mechanisms, executed finite-task evidence,
and work that still needs a model/data contract. It is not a claim that an agent
can read arbitrary neural circuits or find a global neural-network optimum.

## 1. Diagnose the actual computation before choosing a parameter

The five published Hepta research checkpoints have an 85-dimensional input
(43 common-state, 33 mass, 9 bank coordinates), a frozen tanh hidden layer of
width 48, and four affine outputs. The first three rows plus biases contain
147 continuation parameters. The last row plus bias contains 49 Belief
parameters. Terminal decisions are decoded from that belief. These artifacts
are distinct from the actual Pocket4 pretrained Laya encoder and its masked
low-rank output adapters; a shared project name does not establish a tensor or
semantic mapping.

| Requested subsystem | What the audited finite task actually contains | Established evidence | Additional acceptance needed |
|---|---|---|---|
| State representation | Fixed 85-to-48 tanh map; public state, masses and analytic banks | No exact hidden-vector plus legal-mask conflicting-target alias was found in the old complete TRAIN check. A limited output-head impossibility certificate exists. | Causal feature lineage and controlled representation ablations; useful states, tolerances and cost must be fixed before evaluation. Failure to copy all teacher actions does not prove a representation defect. |
| First-Passage / Reset | A sign label at fixed tick 6; REPAIR changes sensor quality | The current task is not a first-passage target and REPAIR is not a latent-process reset. | An explicit stopping-time label, survival/event/censoring convention and reset transition contract. No existing weight index can honestly be labeled a proven first-passage defect in this task. |
| Call / Put | SUBMIT0 and SUBMIT1 terminal utilities are 1-2p and 2p-1 | They share one belief scalar; independent financial Call/Put value channels are absent. | Independent channel definitions, payoff/cost/risk accounting, symmetry/asymmetry tests and a verified tensor map. Pocket4 ACT/ESCALATE is also not this channel pair. |
| Belief | One learned affine head feeding a fixed terminal decoder; a separate own-law analytic posterior is available | Previous Belief-only and analytic-posterior controls did not meet the specified efficacy gate. | Proper scoring/calibration under an independently specified posterior, plus task-value change; a lower belief loss alone is insufficient. |
| Continuation Q | Three affine WAIT/READ/REPAIR scores with first-maximum legal-action decoding | Previous uniform optimal-Q regression reduced proxy loss while worsening utility. In the original radius, all selected teacher continuation orderings cannot be copied. | The current terminal-anchored, occupancy-weighted partial-edit experiment tests a different objective on new schedules without claiming full teacher imitation. |
| NDU value control | Finite own-law transition model, explicit fees, legal masks and a terminal utility | Previously executed own-law Bellman program J improved this finite task; native Bellman replay reproduced supplied-program Q values. | An externally valid global objective, causal costs and prospective environment evidence. Caller-supplied transitions are not authenticated truth, and synthetic utility is not live PnL. |

The historical claims in this table refer to the frozen predecessor package
[9f2d00f](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/9f2d00f79bfe7abc334e51f52a0d16f685656e5d/tools/hcsn/wsp_followup_20261105),
including POLICY_COMPILATION_LIMITS.md and train_margin_certificate. They are
not newly measured outcomes of the present run.

## 2. Use a value-aligned local problem, and retain the no-edit option

Let C be the fixed incumbent, Q_C(s,a) the expected own-law value of taking a
single action and then following C, and a_T(s) the unchanged decoder's best
legal terminal action. The current experiment targets

    Y_a(s) = T_pred(s, a_T) + Q_C(s,a) - T_own(s,a_T).

This puts the continuation advantage on the scale of the actual terminal
decoder. It avoids silently comparing an accurate environmental Q estimate
with a differently calibrated learned terminal score. A fixed mixture of 90%
normalized incumbent occupancy and 10% uniform legal support weights states,
with equal world weight and uniform legal continuation-action weight.

The edit is an exact-head trust-region quadratic, with the unchanged protected
Belief row and original coefficient radius. The direct spectral solution and
projected-gradient control receive identical information, objective, radius,
start and stopping tolerance. Both use the same predetermined five-point alpha
path and full TRAIN own-law selection, including exact C at alpha zero.

This is **parameter fitting without backpropagation**, not fitting without data.
It is a controlled extension for Hepta's analytic task, not a literal repeat of
MIT's discovery rules, which prohibited iterative loss fitting. A certified
optimum of the quadratic is not a global optimum of the discontinuous task
policy, the entire neural network, or live trading utility. Selection is optimal
only over the declared finite path under the checkpoint's own law.

The frozen ablations distinguish the two proposed objective changes, match the
gradient solver, retain the prior MSE head, use one norm-matched random direction,
and include two no-weight-edit controls. All candidates precede validation;
all per-fit gates precede TEST. The same five original fits remain the inferential
units. New nonoverlapping schedules do not create new independently trained
models or rule out unknown historical exposure.

## 3. Native mathematical rejection before spending on an impossible target

For a target continuation ordering, concatenate the three affine rows into w.
For each required pair, a_i is the signed 49-coordinate feature difference
between the target and competitor output slots. The necessary weak ordering is
a_i^T w >= 0. Let C be the stored original head and R^2 = ||C||^2 / 4.

For any nonnegative supplied witness y, define v=A^T y and d=-v^T C.
If d>0 and d^2>R^2||v||^2, no displacement of norm at most R can satisfy all
those orderings. This is the Cauchy-Schwarz separation argument. A weak ordering
is necessary even when the actual first-maximum rule additionally requires a
strict inequality, so its infeasibility also rules out that stronger target.

The new Rust verifier interprets each finite binary64 as an exact integer
multiple of 2^-1074, uses bounded BigInt arithmetic, checks the sign before
squaring and uses strict integer comparisons. It separately evaluates the
conservative F64 rounding relaxation with denominator 2^53-98. No numerical
tolerance or convergence flag decides a proof. The exact stored checkpoint
bytes provide C, and the returned 147 coefficient bit patterns are checked
against the independent Python parser in the actual corpus qualification.

The verifier binds raw checkpoint, witness, state, feature and teacher identities,
validates supplied first-maximum actions, rejects inconsistent duplicate source
rows and bounds input size, rows, concurrent workers and compute time. Hash
equality establishes content binding, not source authentication. The tool does
not independently reconstruct hidden states, authenticate the teacher program,
prove the declaration of hardware rounding semantics, or measure task value.
Those responsibilities remain with the producer and independent semantic replay.

**A certificate blocks an impossible complete-cloning subproblem. It does not
block beneficial partial repair, a larger edit radius, a new representation or a
different policy program.** The present value experiment deliberately tests
partial value improvement instead of repeating full-cloning loss minimization.

## 4. An agent subsystem built from evidence-producing components

REA supplies an agent with interfaces for inspecting and testing a program.
The appropriate analogy here is a content-bound investigation workflow. Binary
reverse-engineering examples do not establish neural-circuit identifiability.
Even this tanh network has hidden-unit permutation/sign symmetries: a useful
circuit claim must survive equivalent parameterizations and causal intervention.

The existing native runtime branch already exposes the artifact/forward, ridge
planning, Bellman planning and guarded patch/recovery components below. The new
certificate fills a distinct rejection path; it does not rewrite the earlier
tools or represent them as new work.

| Stage | Native interface or evidence | Acceptance boundary |
|---|---|---|
| Identify | weight_profiles/open/read/status; raw artifact and request hashes | Model revision, dtype, dimensions, byte mask, tensor map and legal authority must agree. |
| Reproduce | weight_linear_forward and independent task executor | Input/output identity and fixed arithmetic tolerances; no task claim from a shape or checksum check. |
| Diagnose | Analytic invariants, counterfactual/activation evidence, known-answer controls | A proposed circuit explanation needs a discriminating intervention; an agent narrative is not proof. |
| Reject infeasible full-copy targets | New weight_continuation_certificate | Exact proof only for the declared head, rows and ball; never general network impossibility. |
| Plan | weight_linear_ridge_plan; weight_bellman_plan | One bounded quadratic or declared finite DAG. Global optimality is conditional on that exact problem. |
| Edit | weight_artifact_patch; weight_guarded_linear_patch | Expected bytes, allowed coordinates, exact stored-value budget, separate candidate artifact and durable intent. |
| Validate | Frozen validation/test runner and original-world value accounting | Independent records, matched controls, reject/restore for failed per-fit gates, no test-driven retuning. |
| Recover | weight_artifact_restore and guarded same-request journal recovery | Recheck before/after identity, preserve failed attempts, verify restored bytes; unrelated concurrent writer mismatch fails closed. |

The predecessor guarded journal records intent before mutation and requires an
explicit matching recovery request after an interrupted transaction. Ordinary
failed validation can restore the source bytes. Neither mechanism is an
unattended daemon that has already been installed against Pocket4's live trainer.
No production rollout or arbitrary whole-model autonomous repair is claimed.

## 5. Cost and efficacy must be accepted together

At least four costs must be reported separately: diagnostic/feature/teacher
construction; candidate search and edit arithmetic; full validation and rejected
attempts; and deployment inference overhead. Shared costs are counted once.
Worker-internal timers must not be added to their enclosing child-process costs.
The editor's inference tokens/service waiting and measured energy need their own
records; absent records mean unknown, not zero.

The earlier direct-vs-gradient head experiment had a roughly 17.7-fold solver
CPU ratio, but after shared target construction the ratio was only about 1.0275,
and both candidate families failed their efficacy gates. Those measurements
cannot establish a speed advantage at equal useful quality. Likewise, an exact
certificate can prevent repeating one impossible fitting objective but does not
retroactively measure the amount of compute saved in future work.

An acceptable claim of a more efficient optimizer requires a fixed useful-quality
target, all required task gates, a matched strong comparator, measured total cost
and an uncertainty/sampling scope. A failed candidate plus correct rollback is
a qualified recovery behavior, with zero efficacy improvement from the rejected
candidate. It must remain a failure in the scientific report.

## 6. Remaining closure criteria

The independent acceptance package must retain all source/model/protocol hashes,
raw per-world outcomes, candidate paths, every validation gate, exact restored
identities, negative controls and complete process receipts. Native software
tests, corpus arithmetic equivalence and task-value evidence are separate gates.
Repository CI must be assessed at the actual submitted head; a predecessor's
passing run cannot qualify new code.

To close the broader goal still requires: the actual Trader-to-Neuron semantic
map and original fresh-source contract; First-Passage/Reset and independent
Call/Put target definitions; controlled representation changes; new independent
training fits for stronger generalization; and a matched edited/unedited by
generation-configuration factorial for MIT's complete benchmark. The published
Qwen edit replay and short F32 cache checks from the predecessor are useful
engineering evidence, not completion of that benchmark or a fresh Astra
discovery. These gaps must remain explicit even if individual software or
finite-task gates pass.
