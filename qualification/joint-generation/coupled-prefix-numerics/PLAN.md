# Fixed FIT-prefix numerical diagnosis, not a scientific rescue run

The prior campaign permanently failed in seed11 independent-NDU,zero-based
pre-update step117,while its shared coupled-A auxiliary derivative checked relative
residual mass balance. No residual values,validation orcompleted coupled-trained
models were saved. This diagnostic determines what that boundary meant;it does not
relax the old guard,continue the eight-cell campaign orselect a winning model.

## Fixed reconstruction and stop

Use ONLY the exact previous supervised seed11 base andoriginal source/data generator.
Reconstruct117independent-NDU updates with original aligned loss,lr.003,anchor.2,
batch64 andseed+9000 row/full-low sequences. The earlier independent-A arm is not
retrained:it was a separate clone with no effect on this clone's trajectory. Pure
coupled auxiliary calls are omitted during prefix reconstruction;they do not update
parameters or RNG. Retain the original unusedbase forward each step. The failed
pre-update batch is exactly index117,all64rows,no row search/subsetting.

The original strict helper must reproduce the same relative-imbalance refusal at
that batch. Otherwise stop:no later batch/seed is searched. The original failure
had no saved state digest,so evidence is deterministic source/input reconstruction
plus the same refusal,not a comparison to an unavailable original state snapshot.
After117updates,freeze arrays/read-only andverify the model digest remains unchanged
through all references. No further optimizer update,newcheckpoint,validation orTEST.

## Three predeclared numerical references

Compare all64rows with the qualified original FP64 actual CDF-normalized joint law.

1. **Represented:** exact rational arithmetic on the existing binary64 raw policy
   values,without renormalizing either policy. This separates summation error from
   pre-existing policy-total drift. Verify exact identity rA-rB=sum(p)-sum(q).
2. **Simplex:** explicitly normalize each raw policy in rational arithmetic,then
   form the coupled law andits smooth per-row log-weight gradients. This is a NEW
   numerical reference,not an unchanged old profile or a hidden denominator repair.
3. **Extended:** explicitly normalize each raw policy andperform the same operations
   in longdouble. Require genuinely extended hardware precision orstop,no fallback.
   Use the SAME64float64eps floor,sqrt(float64eps) balance and1e-12 marginal guards.

References use fixed rho1.5 on the actual learned-decoder reward. H is the rounded
binary64 exp(-rhoR) table in BOTH rational andextended references;fraction arithmetic
is exact relative to those represented costs,not an exact transcendental exponential.
Log-weight gradients describe the normalized-policy reference graph;they are not
asserted to be gradients of every binary execution of the old softmax. Positive
ties/nonconstant singularities still refuse;constant compositions return zero.
No old gradient is force-computed by bypassing its guard.

## Literal prerequisites and fixed decision criteria

Four literal tests before payload access:extended versus rational normalized law/
gradient;two-head directional FD forA/N;represented mass drift versusexplicit
normalization;ties/constants/inputimmutability. Fixed tolerances:table/gradient
parity1e-12 on moderate fixtures,directional FD7decimal places. No numeric execution
before source freeze/static review.

Record all64-row aggregate residual/balance/closure statistics andtiming byreference.
Require all64exact-normalized andextended rows admitted withthe unchanged thresholds;
all64reference gradients compared;extended/exact joint error<=1e-12,gradient error
<=1e-8,value error<=1e-10;explicit normalization must change the old actual joint and
marginals by<=1e-12. Report failures too,no denominator/threshold retuning.

If these pass andthe represented exact reference still hasrelative-balance failures,
label only **input-mass-closure reference supported on this fixed batch**. If exact
represented arithmetic resolves them,label **transport-arithmetic reference supported**.
Otherwise the reference is not fully supported. Neither conclusion is a generation
quality result orautomatic admission to another training campaign.

## Complete bounded cost and artifact boundary

One completely waited child under the sameexisting synthetic-only shared lock:
5CPU/60wall/512MiB/4MiB,CPU0/onethread,no descendants/network/retry. Exact source and
old failure bindings;one exact base payload. Expected1restore,1clone,117updates,
353forwardbatches/22592rows,1decoder observation/12images,1oldguard attempt/0completion,
64FP64serving tables plus64rows each represented/simplex/extended reference. No TEST
orvalidation generator call,quality scoring/model selection orcheckpoint saving.
Four tests andall reference arithmetic count in wholewait4 CPU. Prior base preparation,
failed campaign,qualification,source/review andunknownsupervisor tails are notfree.

Publish only code,literal fixtures andaggregate diagnostics;no row identifiers,raw
policies,images,model weights orprivate paths. Preserve the original failure andall
earlier scientific gates unchanged. Any later numerical implementation needs its
own explicit profile,qualification,predeclared comparison andresource admission.
