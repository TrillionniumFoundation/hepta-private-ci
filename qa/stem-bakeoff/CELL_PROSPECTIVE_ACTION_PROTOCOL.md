# Prospective diagnostic-action Cell study

Date: 2026-10-24. Additive local phase after implementation/report commit
`28f8d3eea82d96c5fa1cab4b611380b1165c3da5`. Remote CI is outside scope.
Earlier sources, fitted parameters, predictions and evidence remain immutable.
The earlier C archive save was rejected before upload; this phase does not
retry that action or treat local-work authorization as disclosure authorization.

## Questions and input availability

The earlier two-action task selected a fail-to-pass primary and pass-on-both
comparator after execution. That is a curated retrospective relevance task.
This phase instead fixes every proposed action before its outcome is observed.
The primary binary target is whether a real test's **pass/fail outcome differs
between the two supplied implementations**. Both-pass and both-test-failure
pairs are valid negatives. Setup/import/collection errors, skipped/no effective
tests, timeouts and missing observations are unavailable, never negative labels.

Use every declared upstream command plus at most three deterministic same-file
comparators per command, from the unchanged source preparer. Deduplicate exact
runner/argument tuples within each bug before execution. No observed result may
choose a primary, comparator, candidate order or corpus membership. Execute all
frozen unique candidates on both revisions, with the same fixed test tree and
fresh working source for each command. Preserve every attempted condition.
The proposal remains a supplied-change, supplied-test task, not arbitrary test
discovery, fault localization, or general program-correctness prediction.

The predictor contains only the supplied diff, one real test command and its
prepared source/fixtures. Exact character spans identify change and action
regions. Labels, command-selection roles, revisions, project/group IDs and
observed results never select numeric feature content. A single-implementation
prediction cannot use the opposite implementation as an undisclosed input.
The maximum complete predictor is 131072 UTF-8 bytes; oversize/missing source
views remain unavailable, with full proposal denominators retained.

## Source roles fixed before new command outcomes

| Role | Whole projects | Raw bug groups |
|---|---|---:|
| Training | youtube-dl, scrapy | 83 |
| Tuning | luigi | 33 |
| Calibration | thefuck, tqdm, PySnooper | 44 |
| New external holdout | ansible, fastapi, httpie, sanic, cookiecutter | 48 |

All development projects were used previously and are explicitly reused
development data. Previous holdout projects black/tornado are excluded from
this phase. The pinned BugsInPy metadata contains 501 records; project-level
exposure is audited against prior operational and repair study inventories.
Matplotlib is exposed by the earlier repair cohort and is not a fresh holdout.
All 69 declared primary command lines in the five new projects are retained.
Cookiecutter's `tox <pytest-selector>` metadata requires an explicit adapter
to direct pytest, preserving the original command and declaring the runtime
condition; no hidden tox hooks or source repairs are inferred.

Source acquisition, prepared test candidates, runtime profiles and all code
hashes must be sealed before their corresponding benchmark execution. Runtime
repairs, if required, apply uniformly to an entire affected project, preserve
all prior attempts and cannot use model scores. No missing dependency is fixed
by changing the intended source revision or relabelling its outcome.

## Shared features and private learning

Three declared feature conditions use only clean source fields:

1. Three identifier-overlap scalars: Jaccard and the two directional coverages.
2. Signed SHA-256 identifier-set vectors, 384 dimensions per field, followed by
   `[change * action, abs(change - action), cosine, Jaccard]` (770 dimensions).
3. Fresh Granite 97M field vectors with the same 770-dimensional interaction.

Native fields use the pinned Granite inventory, complete 192-token windows
with 32-token overlap, one owner, four Torch threads and batches of 16. Exact
field bytes may be deduplicated before encoding, with every row/field/source
binding preserved. Prior contextualized curated-choice chunks are not silently
relabelled as independent single-action field vectors. Zero-norm/missing fields
are explicit unavailable features. Each condition has a distinct feature identity.
Empty non-keyword identifier sets are unavailable for both source-only baselines;
the native condition may retain those rows if both real field vectors exist.
All matrices retain source order with an explicit availability mask. Training
and scoring use finite available rows, and comparisons additionally report the
common group/row support and per-condition coverage; an unavailable value is
never silently replaced with a zero feature vector.

Heads start from scratch. Training budgets are 8, 32 and 64 distinct bug groups,
at most one selected action example per group, seeds 7/17/29. A budget lacking
class/group support remains unavailable; 128 is unavailable from the 83-group
training pool and is never renamed. The full pool's labels are used for balanced
sampling and are counted separately from selected gradient examples. Tuning
and calibration use every applicable action with each bug's total weight one.

Retain prior, exact full-text lookup, full-text BM25, dense nearest, prototype,
linear, gated and rank-4 residual where applicable. Use the existing fixed
regularized training grid and 100000-private-parameter ceiling, accounting for
all calibration state and search paths. Additional direct identifier relevance
is a no-fit ranking control. Selection uses tuning data only, with deterministic
ties toward simpler/lower-cost candidates. Seal all preparation before any new
holdout model score. Previously observed holdouts are not fresh validation.
The predeclared tuning selector compares prior, prototype, linear, gated and
residual in that simplicity order; exact, BM25 and nearest retrieval remain
separate reported controls with their own eligibility and coverage.

## Bounded calibration

The old standardized scale/bias fit can extrapolate extreme probabilities even
when its optimizer converges. The new additive alternative uses non-sharpening
scales `{0, 1/16, 1/8, 1/4, 1/2, 1}` and the effective loss-weighted training
prior. A group-weighted, smoothed calibration prior is the explicit no-evidence
endpoint. Mix evidence with that prior using fixed weight `g/(g+16)`, where `g`
is the number of independent calibration groups. Choose scale by calibration
NLL, exact ties toward smaller scale. Report every candidate and deterministic
probability/NLL-excess bounds; these bounds are not uncertainty intervals or
proof of learning. A separate complement-symmetric mode is reserved for any
explicitly declared old curated-choice development diagnostic.

## Evaluation, qualification and cost

Primary action metrics weight each bug total one: BA, positive recall, NLL,
Brier, ECE and fixed-threshold coverage/risk. Threshold remains 0.7, with the
existing declared coverage curve; abstention is never success. Source-group
bootstrap intervals resample whole bugs and preserve all their candidate rows.
Seeds, actions and repository-correlated labels are not independent trials.

Report each predeclared method, and the method selected using tuning only.
Report proposed, source-available, feature-available and valid-outcome counts
separately for every project. Candidate-ranking success uses the full proposed
group denominator; unknown outcomes do not become successful or negative labels.
Any replayed test-order cost is labelled counterfactual replay of recorded
observations, not a new live sequential agent run. An oracle order is only an
upper bound, never a competing deployable policy.

Freeze ranking rules before any new model score: rank eligible candidates by
positive probability, with exact ties by the pre-frozen command hash. Report
known-positive success at the first one, two and three proposed actions, using
all 48 proposed holdout groups as the denominator. Missing source/features and
arm-ineligible candidates cannot generate a scored recommendation; groups with
no recommendation are abstentions. Report unknown-outcome selections separately.
Also report the first recommendation restricted to positive probability at
least 0.7. The no-information order is the original sorted command hash, and
direct identifier relevance ranks by source-only Jaccard, with the same ties.
For counterfactual full-order replay, append unscored candidates in hash order
and accumulate the recorded pair wall work until the first known positive,
retaining groups with no known positive and all unknown outcomes separately.
This is an observed-outcome replay, not estimated wall latency of a live agent.

Engineering closure requires complete immutable proposals, all-attempt outcome
accounting, no target leakage, bound-correct calibration, faithful private-state
replay and explicit full costs. Scientific usefulness additionally requires
discrimination and useful group decisions relative to the applicable fixed
baselines, together with probability quality and nontrivial coverage. Missing
independent support, a prior-only selector, or a failed comparison remains a
negative/unresolved quality result; execution completion cannot qualify a model.

Count data acquisition, every test attempt, field extraction, private training,
baselines, calibration, replay, source retention and recovery. Unknown timing
remains unknown. Some processes may overlap; stage wall work is not elapsed
time and RSS peaks are not summed. No production authority is granted:
all new artifacts remain `SHADOW_ONLY / DENY_ALL`.
