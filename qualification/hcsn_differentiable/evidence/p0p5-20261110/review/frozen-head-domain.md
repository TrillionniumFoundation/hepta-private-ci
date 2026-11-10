# Frozen random head: independent output-domain review

## Finding

All 11 classes are reachable for each of the three actual heads under the outer output domains of raw GRU, PLIF and event-time LIF. A class being impossible to predict is therefore not an established explanation for the observed memorization failures. The fixed random head nevertheless imposes large and unequal probability constraints on bounded cores. A common trainable linear adapter removes this particular restriction and is a justified change of experiment; it does not establish downstream benefit or adequate training.

## Actual inputs and methods

The analysis uses head weights extracted from saved initial checkpoints for seeds 101, 211 and 307, each with width 16 and 11 classes. The input file SHA256 is `6f26ae3131ef618abb78377b929ddc2b1b7cfe1f328de606a3ec38ad4e5da4be`. A separate Torch reconstruction of the module tensor digest verifies all three recorded head identities. No core was trained or retrained for this analysis.

Write the frozen output map as logits `W h + b`. For each class, the analysis maximizes its minimum logit margin over every competing class.

| Raw core output domain | Method | Scope |
| --- | --- | --- |
| PLIF: 16 binary coordinates | Exhaust all 65,536 states; retain argmax counts, maximum margins and maximum softmax probabilities | Exact finite domain enumeration for the supplied FP64 weights |
| GRU: 16 coordinates in [-1,1] | Linear programming for class margin; convex NLL minimization with a Frank–Wolfe gap certificate for probability | Outer domain; a temporal GRU is not proven able to emit every witness on real data |
| Event LIF: nonnegative coordinates | Linear programming for a positive-margin state and a positive-cone direction | Outer domain; no claim that actual dynamics produce the witness |

## Reachability and confidence limits

All three domains have a strict positive-margin witness for every class, for every seed. For the nonnegative cone, each class also has a direction along which all competing logit gaps grow; its softmax probability can approach one in this unconstrained outer domain. Raw binary and bounded GRU outputs have the following per-class probability maxima. Each interval below is the minimum to maximum across the 11 classes, not a confidence interval or an observed model-score range.

| Seed | PLIF per-class maximum probability | GRU per-class maximum probability upper-bound range | Head rank / condition number |
| --- | --- | --- | --- |
| 101 | 0.163891857–0.317303835 | 0.326870999–0.500541832 | 11 / 8.630623 |
| 211 | 0.120389777–0.387251784 | 0.254756574–0.599138403 | 11 / 7.783828 |
| 307 | 0.133296189–0.304362080 | 0.318780046–0.601097354 | 11 / 7.841438 |

A pronounced geometric asymmetry occurs for PLIF seed 211: only one of the 65,536 binary patterns is classified as class index 7. Its best possible margin is 0.01746678352355957, and its maximum softmax probability is 0.12038977685836551. This fraction describes the enumerated binary cube; it is not the probability of a learned spike pattern. It does not prove an optimization failure mechanism.

These probability ceilings create irreducible NLL and probability-calibration restrictions even if a core could classify every example correctly. For illustration only, if labels were uniform and each example could choose its best admissible state independently, the resulting NLL lower bounds would be:

| Seed | PLIF NLL lower bound | GRU NLL lower bound |
| --- | --- | --- |
| 101 | 1.574909479 | 0.889718398 |
| 211 | 1.591713928 | 0.905142390 |
| 307 | 1.560245326 | 0.874564057 |

These uniform-label examples are not the UCI label distribution. Actual aggregate loss bounds would require weighting the per-class bounds by the declared evaluation labels. Accuracy and macro-F1 do not inherit the same hard probability ceiling, so the result cannot by itself explain failure of the 95% accuracy / 90% macro-F1 memorization rule.

## Numerical certificate for the GRU probability bound

For target class y, let f(h) be softmax negative log likelihood. This function is convex in h. At any feasible h in the box, its gradient gives the lower bound

    f* >= f(h) - g,    g = grad f(h) · h + ||grad f(h)||_1.

Therefore `p_y,max <= exp(-(f(h)-g))`, while `exp(-f(h))` is an attainable value at the retained witness. The largest measured convex optimality gap across all 33 class/seed cases is 8.365841353e-11. The report retains both bounds, gaps and witnesses. This is a convex-duality calculation evaluated in FP64, not an interval-arithmetic proof controlling all rounding error. It is stronger than merely reporting an optimizer maximum.

The margin LP is also checked by a direct dual expression. With nonnegative multipliers lambda summing to one over competitors, the maximum box margin is at most `lambda · offsets + ||lambda^T D||_1`, where rows of D are target-minus-competitor weight differences. Primal witnesses and dual simplex weights are retained. The largest primal/dual discrepancy is 1.11022302463e-15.

## What a common adapter changes

All three actual W matrices have full row rank 11. Let R be any right inverse, so W R=I. A trainable width-to-width adapter z=A h+c can realize an arbitrary 11-class linear readout V h+d by choosing

    A = R V,    c = R(d-b).

Then the frozen head computes `W(Ah+c)+b = Vh+d`. This is functionally a trainable linear readout over each core’s state. It removes the restrictive pairing of a bounded/raw state domain with an unchangeable random classifier. It should be described that way, even though the shared head tensor itself remains frozen.

The analysis explicitly constructs one adapter per seed for `V=20*[I_11 | 0]` and d=0. The eleven binary states h=e_y then predict all eleven classes with margins about 20 using the same adapter. The maximum linear-map reconstruction error across the three heads is 3.56354905132e-14. This demonstrates a removal of an output-map restriction, not that a particular temporal model can learn those states or that SGD will find the adapter.

Each 16-to-16 adapter adds 272 stored trainable real scalars and its matrix-operation cost. At full head row rank, the corresponding linear-logit function has 187 effective coefficients; the remaining adapter directions lie in the frozen head’s null space. All seven arms should receive the same identity-initialized matrix and zero bias, and their added parameters, optimizer state and compute should be counted. Existing S4D/HCSN internal output maps remain part of their core costs.

## Consequence for the next experiment

Retain the original 36 raw-interface fits as historical development evidence. Initialize and train every new candidate afresh under the common-adapter regime, preserving the same actual shared frontend/head identities and predeclared resource/selection rules. Do not merge old and new scores into one comparison or attribute any improvement automatically to HCSN’s regenerative physics. Report adequacy and task quality from the new run as observed outcomes.

## Artifacts

- `frozen-head-domain-review-v1.json`: all witnesses, weights of dual certificates, confidence bounds and constructed adapters.
- `review_frozen_head_domains.py`: independent LP, enumeration and convex optimization script.
- `actual-frozen-heads.json`: checkpoint-extracted weights, biases and source identities.
- `frozen-head-identity-verification-v1.json`: independent tensor-digest checks.

Analysis JSON SHA256: `83e34deaeb221d31a4ce7e1b292a2fd3fd26ec6b430c4ba90af7c4697f98aab2`. No model training, E confirmation or HCSN benefit credit is granted by this calculation.
