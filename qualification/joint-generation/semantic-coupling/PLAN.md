# Maximal semantic coupling: fixed prospective serving comparison

## Motivation, operator and non-claim

The existing joint-NDU plus semantic-transport service still has about4.5%-4.7%
cross-modal inconsistency on the partial-command aggregate. Independent marginal
sampling can disagree even when both marginals put high mass on the same scene.
Change the serving dependence, not the learned model or any target/utility input.

After unchanged explicit-word transport, match text/image slots by OBSERVED decoded
semantics. Put d_s=min(p_s,q_s) on each matching pair. The remaining marginals have
disjoint semantic support; couple them by their normalized product. Thus agreement
is sum_s min(p_s,q_s), the largest possible among couplings with those marginals.
Each individual semantic marginal (including all unspecified joint attributes)
is preserved mathematically; floating implementation verifies1e-12 absolute error.
No epsilon support expansion, target labels, reward table or new decoder is allowed
in the operator. Incompatible numeric masses reject, not repair. Identical policies
produce a diagonal law; residual-zero checks are exact. No learning-benefit claim.

This is a NEW explicit dependent joint serving profile, not the original independent
law. Original transport API/default remains unchanged. New schema/mode/model and
observed maps bind identity; loading requires explicit expected mode/model. Scalar
sampler consumes supplied U[0,1) and its full table CDF, with no RNG/fallback. Actual
sample law normalizes only the finite-precision total;1e-12 marginal checks disclose
the numerical rather than bitwise nature of preservation. The operator separately
checks CDF-normalized marginals, rejects incompatible mass, and worker scores the
CDF-normalized actual law (not an unnormalized table). Joint MAP is separately
reported; unchanged marginal-greedy metrics are not misnamed the joint MAP decoder.

## Frozen models and matched comparison

Reconstruct the SAME4 prior aligned A/J models:seeds11/23,300 updates,batch64,
lr.003,anchor.2,rho1.5,original full sampler seed+9000 and same full/low masks,
shared encoder/frozen learned decoder,all4 previous utility branches/both anchors
and original unused base forward. All4 must exactly match their predeclared final
digests. No new training for coupling. Independent/coupled laws share each final
model, so this is a paired serving comparison, not two separately billed trainings.
All4 models fixed before validation; all costs of reconstruction are charged.

Train1560rows/260groups;validation516rows/86disjoint groups,full+low. Primary312
partial-command rows,macro channel average;allrows/channels and two original bases
also reported. No TEST data,checkpoint selection,new saved model payload or held-out
confirmation. Reused synthetic validation cannot certify generalization.

## Predeclared gates and complete metrics

Content-control primary: for BOTH seeds and BOTH A/J trained controls, coupled minus
independent must have original joint-CE gain>=.005, joint-success and consistency
gains>1e-10, absolute correct-text mass/greedy-text/pixel-MSE changes<=1e-12; all
per-request two-marginal/maximal-agreement checks must pass. Structural joint-success
and consistency gains are explicitly structural, not newly learned capability.

Keep NDU-versus-A gates SEPARATE under each service:original joint CE gain>=.005,
text mass/greedy text/joint success changes>=-1e-10,MSE increase<=1e-10 in both seeds.
The prior greedy regression is not erased by a successful content-control gate.
No metric replacement,mode/rho tuning or favorable-seed selection is allowed.

All scores use the ACTUAL 12x12 joint table and reward from observed decoded strings
and learned pixels. CE uses the original exponential utility, not product marginals
when coupled. Marginal MSE comes from the joint's image marginal. Report also joint
MAP success, marginal greedy pair success, expected reward and unspecified-content
preservation. Dense finite-law enumeration provides exact expectations up to floating
roundoff,not sampled empirical estimates.36 fixed sampler draws check support only.

## Qualification and complete resource receipt

Eight literal tests:equal policies,disjoint support,partial overlap/marginal bound,
permuted observed semantics,all36commands,explicit distinct roundtrip/rejection,
positive CDF intervals,invalid probability/uniform rejection. New helper has no
training target/reward/model payload interface. Existing helpers copied unchanged.

One completely waited CPU0/single-thread child,20CPU/90wall/512MiB/4MiB,under the
existing NEW synthetic-only shared lock; refusal/failure stops without retry. Eight
tests precede payload access. Exact2base allowlist,no descendants/network. Counts:
2restores,4clones,1200updates,3612forwardbatches/236592rows,2decoder observations/
24images,12scalar transport checks,6192joint tables/891648table entries,12384marginal
checks plus12384CDF-normalized marginal checks,6192agreement-bound checks,6profile roundtrips,36sampler draws. Extra decode0.
New table formation and scalar transport/binding costs recorded per channel/model;
baseline table path is vectorized,so these timings are not equal-overhead kernels.
Whole waited child includes imports/tests/validation/output/exit. Inherited base
preparation plus source/review/supervisor-tail costs remain additional,not zero.
Matched paired models/common caps do not imply equality of actual total spend.
