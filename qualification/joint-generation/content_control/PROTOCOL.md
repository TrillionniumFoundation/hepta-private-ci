# Content-state refinement: TRAIN-only registration v1

Base: `0aca16714390ca045a53cece9644992b7990fc9c`, PR #3451. Independent
branch `research/content-control-budget-20261023`. Main cloud task reported by
the parent: `01a167f7-8443-7559-aac3-b5204b6ac0d5`. This environment is an
independent delegated cloud workspace, not that task or the user's computer.
No formal dataset/result, opening-marker contents, or evaluator may be read/run.

The completed historical diagnostic reads only explicit base/selected model
files, anchor/additive build receipts and the CORE plan, then reconstructs only
CORE TRAIN. It is development cost, not another confirmation. Its evidence is
`runs/content-control-train-diag-20261023/diagnosis.json` (0.309 CPU seconds).
Additive utility dominates the 0.2-CE logit gradient on easy rows (~8.5x), but
can vanish or oppose it on rare wrong rows. Different useful update counts and
CPU shocks confound historical seed differences. This does not explain, overturn
or qualify the failed CORE result. No causal attribution is claimed.

## One candidate and fixed controls

Hypothesis: a small recurrent content-state correction can spend less useful
training work than updating the entire encoder and improve decoded outputs with
the same CE anchor. This is falsified by absent A-H gain, worse effective static
quality/cost, or greedy loss >0.02. No further architecture/weight/seed search
is authorized by this registration.

Use only the existing CORE TRAIN generator, once. In every source class, source
index divisible by four is inner validation; all other physical sources are fit.
All eight instructions and both variants stay with their physical source.
The 144 fit and 48 inner-validation sources are disjoint; new shared bases see
only fit sources. Neither old validation nor any old/new formal fold is built.
Seeds 11/23/47, hidden32, decoder300, full-view pretrain500 at lr0.003, batch64.
Each seed's fixed base is shared across all arms. No old trained model is reused.

Arms: dense full CE S; dense 0.2-CE H; dense 0.2-CE minus additive utility A;
refiner 0.2-CE H_R; refiner 0.2-CE minus the same additive utility A_R.
Exactly one new architecture, three fixed LRs 0.001/0.003/0.01 per arm, no
supervision-weight/risk search, no early exit and no additional hidden policy.
Every dense arm updates encoder and both heads. Each refiner has zero-initialized
W_T/W_I (32x12), C_T/C_I (12x12), b_T/b_I. Its base is frozen after pretraining.
For fixed h and current logits t,i, T sets t'=t+hW_T+softmax(i)C_T+b_T;
I analogously sets i'=i+hW_I+softmax(t)C_I+b_I. J applies both from the same
previous state. Each single-head action uses one unit; J uses two. Exhaust all
legal two-unit fixed sequences TT/TI/IT/II/J; no semantic budget is a hardware
cost equality claim. h remains fixed in this minimal candidate. Nontrivial
hidden-state control and sequential policy learning are deferred.
Dense adaptation uses the existing native Adam implementation; the much smaller
refiner uses the original NumPy Adam equations with its own six parameter arrays.
The actual shared C compilation is needed by the dense effective controls and
is conservatively attributed in full to every arm, never charged as padding work.

Training optimizes the mean loss over all five paths, backpropagating through
cross-head softmax feedback and shared residual parameters. Each path uses the
unchanged joint decoded outcome table and independent categorical law. Losses,
gradients, parameter deltas and all candidates are retained. There is no
product-of-mixture-marginals approximation. No risk objective is changed.

## Budget and selection

Every arm has the original **10 CPU seconds and 12 billion declared operator
units** complete-build caps. Charge full common data/three-seed decoder/base
training/compiler/export cost to every arm. Feature caching is additionally
charged in full only to both refiners. Each arm gets the same remaining-resource
allocation rule: reserve 2 CPU seconds and 500M units for validation/search/
exports/service; divide the remaining training allowance among nine seed/LR
candidates. One candidate trains until its actual CPU or work allowance is
exhausted. Round rotation counterbalances five-arm order. No unexecuted work or
padding is charged. No residual updates, LR reselection, threshold fitting or
run repetition after scores. Caps are ceilings, not equal measured consumption.
Any actual cap violation invalidates this run and remains retained.

Each dense candidate scores inner validation once. Each refiner candidate scores
all five fixed paths once, explicitly paying this larger search. Select one
global LR/path per arm by mean three-seed raw decoded utility (fixed list order
breaks ties). This exploratory selection does not estimate independent generalization.
Selected models get actual full-view, categorical, PNG/hash/JSON service, one
decoder-corruption check, and an external hand-RGB export/reload check. Charge
all this to the arm, including observations outside service timing. Report build
and service separately; amortize full three-seed build/3 over H=100000 requests
per seed with the original price0.02. Service CPU is conditional on this one
execution wave; no cross-wave CPU confidence claim. No model is charged another
arm's training, and no advantage is claimed from raw operator counts alone.
The price denominator is one actual pre-adaptation base11 service calibration on
64 evenly spaced fit rows, executed and charged during shared preparation before
any candidate score. Service uses the common Python batch/output path; native
batch serving is not qualified or credited by this study. Final JSON archival
and descriptive statistics are recorded separately from model build work.

After all candidate selection, A_R's five path values give per-row and
physical-source oracle headroom. These are label-known upper bounds, not a
deployable policy. Only if mean source-oracle headroom >0.002, fit exactly one
ridge initial-state gate per seed (ridge1e-3, features h,p0,q0,constant), using
fit sources only, all five TRAIN counterfactual values, and evaluate once on
inner sources. Charge this separately as prospective gate-development cost,
never hide it in the static A_R claim. No larger/feedback policy is trained.
Deterministic updates reveal no new external information; an initial gate is
essential before attributing a gain to sequential feedback. Every failed gate
and all seed/source outcomes remain visible. Descriptive paired seed/source
bootstrap intervals use 2000 replicates/seed77431; they are selection-contaminated
TRAIN diagnostics, not confirmation p-values or familywise coverage.

## Independent confirmation draft (not executable or authorized)

Before ANY future test opening, the parent must review the complete history:
r1 narrow padded pass; r2 t1--t11 TRAIN/validation failures including t7/t8
preparation failures; all controller/OOF/timing/codec diagnostics; CORE t1 TRAIN
construction failure and sole CORE c1 t2 formal failure; this diagnostic and
every candidate/run/gate failure. Preserve every original file and exit status.
r2's formal test remains unopened; r1 and CORE c1 remain permanently consumed.

A later protocol must freeze new physical-source provenance and disjoint image
hashes, source generation/ownership, exact source/seed/endpoint/sample counts,
search and complete costs, selected checkpoints, experiment-wide once-only
marker plus run marker acquired BEFORE constructing fresh formal inputs,
failure/interrupt consumption, all raw outputs and statistics. TRAIN source
reuse, a directory rename or a fresh noise variant is not independent evidence.
No such marker or formal split is implemented here.

Error control must cover repeated scientific attempts. Old unadjusted tests
cannot retroactively be put into a new 5% family. Report their nominal alpha
and outcomes, distinguish retrospective/exploratory evidence, and obtain parent
agreement to a forward family with a genuinely unused error budget. One example
is a NEW prospective family alpha0.01, at most one registered confirmation,
two-sided seed/source intervals with all required contrasts/endpoints passing
an intersection-union gate; secondary wins cannot replace a failed requirement.
That gives prospective-family control only. It does **not** make cumulative
historical FWER 1% or 5%. A lifetime bound requires a reconciled list of prior
looks/nominal alphas and a valid residual alpha budget; if unavailable, no
lifetime-controlled claim may be made. No repeated-look optional stopping.

## Sources and scope

The actionable evidence is local TRAIN gradients plus existing decoded reward
equations. Related primary literature motivates modality-specific state updates
and recurrence, not a prediction of success here:
[UniDiffuser](https://proceedings.mlr.press/v202/bao23a.html),
[PonderNet](https://arxiv.org/html/2107.05407),
[risk-sensitive stopping](https://arxiv.org/pdf/1912.02486), and
[Adjoint Matching](https://arxiv.org/html/2409.08861).
This code implements no diffusion, stochastic control theorem, learned halting,
NDU superiority, natural-image model, AV generation or open-world capability.
The separately considered natural-gradient literature was read but no such
candidate was implemented or trained. Exactly one new refiner is studied.

## Pre-score implementation repair v2

The first build at source/freeze `512b0182a7` exited1 before any base content
update, candidate, validation score or selected model. Its bound wrapper's
`clone()` retained instrumentation; CachedObjective correctly refused double
accounting. All data, compiled library, 300 decoder updates (37,616,283 units),
partial ledger, traceback and original 1.554477821 CPU-second receipt remain in
`runs/content-control-train-r1-20261023*`. This is additional failed R&D cost.
The repair calls the existing plain JointModel clone explicitly and adds a
hand-fixture regression. It also attributes ledger/scheduler setup CPU to every
arm, closing a pre-score bookkeeping gap. Objectives, architecture, data/split,
all candidate counts, selections, caps and thresholds remain as registered.
No score informed this repair; a new committed source freeze must precede the
replacement build. No score-based rerun is permitted.
