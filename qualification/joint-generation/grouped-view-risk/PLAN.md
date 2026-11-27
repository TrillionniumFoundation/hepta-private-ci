# Equal-group input-view AND output entropic-risk qualification

SOURCE ONLY; no numerical execution by producer. Independent static review and
separate once-run admission required. This qualifies a new objective/chain, not
science, model updates, dataset generation or a benefit claim.

## Definition and sign/normalization proof
Legacy utility.joint_value_and_grad returns per-row CE_i and logit gradients d_i
of negative MEAN row CE, hence d_i=-(1/n)dCE_i/dz_i. This sign and normalization
are confirmed in unchanged source for both rho=0 and rho>0. Rewards are fixed
constants, bounded[-.35,1], with12categorical outcomes perhead. No reward gradient.

Partition n=G*K rows into contiguous equalK blocks, labels exactly repeated
0..G-1. Define groupCE_g=-(1/rho)log[(1/K)sum_i exp(-rho CE_i)] and minimized
L=-(1/G)sum_g groupCE_g. Chain gives dL/dz_i=K*w_i*d_i, where
w_i=softmax_withingroup(-rho CE_i). Indeed n/G=K; no missing or duplicate1/n.
The joint view/output law assigns probability p_i(a)q_i(b)/K to each group's
view/outcome. Its negative entropic CE equals this nested definition by the tower
identity when all boundaries use the same fixedrho. The tests independently
flatten allview/output events and compute tilted marginal gradients to verify.

rho0 uses arithmetic groupmean and EXACT original rowgradients with multiplier1.
K1 returns exact original CE/gradients, bypassing unnecessary floating arithmetic.
Identical CE rows yield multiplier1; identical-row CE parity is within binary64
roundoff, not a universal bitwise transcendental-identity claim. Constant reward
has zero gradients to qualification tolerance. Zero-sum logits gradients retained.
Use shifted exponentials and log of mean exp (logsumexp minus logK), noepsilon,
probability floor, clipping, newreward/rho, STE, or unbiased-Adam assertion.

Explicit GroupRiskProfile(mode,rho,K) supports onlyrho0/1.5, bounded positiveintegerK,
mode equal-group-input-output-entropic-risk-v1 and distinct objective schema/key.
Metadata binds grouping convention, normalization and exclusion of anchor. Oldrow
objective/mode rejected. No model checkpoint compatibility claim. aggregate_rows
can compose a DIFFERENT qualified rowCE/gradient pair only if it has exactly the
same negative-mean-row convention; aligned/coupled science still needs its own
integration review. This qualification's jointwrapper uses legacyindependent law.

Reject empty, noninteger/bool/float labels, missing/noncanonical groupids, interleaved
or heterogeneous group sizes, nonfinite inputs/outputs, wrong policy dimensions,
mode/rho, rewards outsidefixedrange. Group/view permutation test relabels blocks
canonically after permutation; arbitrary interleaved label support is not implied.
No gradient or mutation of rewards/groupids. Group gradients do NOT includeanchor;
ordinary rowmean anchor.2 must be added separately, never multiplied by riskweights.

## Fixed literal tests, not datasets
Six tests, handmade2groupsx2viewsx12classes, boundedfixedrewardtable:
1. Eight central finite-difference coordinates across bothheads/bothgroups, eps1e-6,
absolute gradient tolerance2e-8.
2. Analytic group-chain versus direct flattened view/output CE and independently
derived tilted-logit gradient;2e-15 tolerance, chainweights1e-15; reward unchanged.
3. rho0 andK1 exact gradient parity with originalutility, unit multipliers.
4. Identicalrows, constantreward and zero-sum gradients (2e-15 tolerances).
5. Block/view permutation equivariance after canonical relabelling (2e-15).
6. Grouping/mode/rho/nonfinite/boundedreward/empty rejection and identity separation.
No fixture imports model/dataset code. No random search or qualification retuning.

## Qualification execution proposal
Oneexisting syntheticlock, nonblocking/no replacement/no retry;CPU0/one numerical
thread,5CPU/30wall,512MiB/4MiB. Complete wait4 aftersuccess/failure/kill records
actualCPU/wall/RSS/exit. Entire fixturework/imports/checks inside childCPU; source,
review, historicalresearch and supervisor tail additional/nonzero. Memory-only
literal arrays,0modelrestores,0trainingupdates,0datasetrows; boundednewRUN_ONCE only.
Immutable sourcefreeze. Numerical tolerances are prospective, not run-selected.

## Later science outline (NOT implemented or admitted here)
Fixed source-masked FIT-source-supervised bases. A,rowN,groupN all use SAME grouped
batch:8distinct contentgroups x4of6fixedscheduledvariants x2full/low=64rows;
300steps, identical8group schedule and4variantchoice.2folds xseeds103/107 =>
12models from4newbases. Group label is content scene/instruction group, not target
class. Risk covers uniformdraw over selected inputviews plus generatedoutcomes.
Every arm computes raw/aligned fourbranches plus groupaggregation equally; choose
A/rowN/groupN only for utilitygradient; same ordinaryrowmean anchor.2 separate.
Source labels onlyownFIT, nominalmodel/optimizer/decoder schedule unchanged.
Allmodels/calibrators freeze before evaluation; sameFITtemperature algorithm and
original5gates, existingstudiednoise clearly disclosed. Newgroupbatch affectsA and
rowN too, so no oldiidmodeldigest reproduction expected or claimed.
PrimarygroupN−A ANDgroupN−rowN must each pass all8unpooled originalgates; preserve
A,rowN,allnegative results. No guarantee input-robustness objective helps, and no
ceiling-driven threshold changes. Need separately frozen sampler/worker/fullwork
ledger and independent admission before any scientific run.
