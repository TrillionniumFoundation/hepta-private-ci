# Objective and attribution contract

## Delivered utility

The fixed scoring contract reads the quantized 56×28 grayscale PNG and the
actual caption. Let text digit error, relation error, image digit error, and
text/image disagreement be fractions in `[0,1]`; let pixel MSE compare the
decoded PNG to the target. The delivered utility is

\[
U=1-2(0.30E_{text}+0.15E_{relation}+0.35E_{image}
       +0.10E_{disagreement}+0.10\operatorname{MSE}).
\]

The recognition model is fixed; the training reward recognizer and qualification
audit recognizer are distinct restored checkpoints. Caption parsing and the
utility arithmetic are independently implemented by the auditor. Both scoring
paths intentionally share the same fixed audit recognizer at qualification.
An invalid caption receives maximal text, relation, and disagreement errors.
CE is computed on actual delivered utilities, not training losses or captions
silently repaired using target labels.

## Conditional exponential-moment controller

For public initial context `h`, candidate plan `a`, and delivered utility `U_a`,
the target is

\[
M_a(h)=\mathbb E[\exp(-\gamma U_a)\mid h],\quad \gamma=2.
\]

The network produces raw scores `z_a` and predicts

\[
\widehat M_a=\exp[-\gamma\tanh(z_a/\gamma)].
\]

Because `U` is bounded by `[-1,1]`, its moments lie in the prediction's closure.
The transformation is strictly decreasing, so the registered deployed
`argmax(z)` is exactly `argmin(M_hat)`. Squared error against observed
`exp(-gamma * U_a)` is a proper conditional-mean regression objective. This
fixes the previous soft training-plan versus greedy deployment discrepancy.
It does not prove finite-sample calibration or globally optimal state dynamics.

The encoder context is detached before the gate, so this head's regression
does not silently differentiate through the discrete recognizer or delivered
utility. The encoder still receives the generator's reconstruction gradients.

## Generator update and retention

For each plan, the supervised per-example proxy is

\[
\ell_a=\operatorname{BCE}_{pixels}
       +0.7\operatorname{CE}_{caption}
       +0.25\operatorname{CE}_{digits}.
\]

The generator is updated using

\[
L_G=\frac1B\sum_i w_i\ell_{a_i^*}
      +0.1\overline\ell_{all\ plans}+0.3L_{teacher,clean},
\quad a_i^*=\arg\max_a z_{ia}.
\]

The uniform arm has `w_i=1`. The risk arm uses

\[
w_i= B\frac{\exp(-\gamma U_{i,a_i^*})}
                  {\sum_j\exp(-\gamma U_{j,a_j^*})},
\]

with the weights detached. Clean teacher distillation combines pixel-probability
MSE and a 0.1-scaled caption KL term at the same plan and latent noise. The old
teacher and both observers remain frozen. All encoder, controlled transition,
pixel decoder, and caption decoder components actually change in the trained
checkpoints; the selected checkpoints and interpolation are independently bound.

Training uses clean input with probability one half and each of three stress
conditions with probability one sixth. Qualification uses one quarter per
condition. Extra clean replay is an explicit retention regularizer; this
generator proxy is not an unbiased gradient of the qualification objective.
Its negative comparison against uniform training is therefore direct evidence
that these particular risk weights do not improve the whole delivered policy.

## Budget accounting

Each seed/updated arm receives all 600 steps, batch size 32, and the same
validation candidate grid. The full training counts per arm/seed are:

| Operation | Count |
| --- | ---: |
| Model encodes / teacher encodes | 19,200 / 19,200 |
| Model transitions / teacher transitions | 153,600 / 153,600 |
| Model decodes, free plus teacher-forced | 153,600 |
| Teacher decodes | 76,800 |
| Actual PNG roundtrips | 76,800 |
| Observer digit examples | 153,600 |

These are declared logical calls, not hardware FLOP or dollar measurements.
Within each seed, source/noise schedule hashes and all these counts match.
Recorded training CPU times range from about 73.8 to 78.6 seconds per arm on
this host, excluding validation selection. The raw selection records retain
all candidate measurements. Selection work is the same grid for both arms.

All three deployed arms use one encoder, one gate, two controlled transitions,
and one decoder. Descriptive batch timings include this entire inference path;
PNG/text delivery time is separately recorded. Inference timing order was not
randomized, so the reported single-host numbers are not a timing superiority
test. Training overhead is not amortized into an invented per-output price.

## Selection, intervals, and attribution limits

Validation comprises 64 source pairs under four conditions and 128 separate
clean-retention pairs. The checkpoint grid is 200, 400, 600 steps and interpolation
strengths 0.5 and 1, with the original eligible. Selection maximizes validation
CE subject to clean CE no lower than original minus 0.005; ties favor the
smaller update then earlier checkpoint. This rule is sealed before qualification.

Qualification has 512 new test pairs and 512 separate retention pairs. The
5,000-replicate paired bootstrap resamples source pairs, keeping all associated
conditions and the three fixed seeds together. The two primary generator
comparisons use 97.5% intervals; neither intervals nor the retention margin were
chosen after test results. These intervals do not establish training-seed or
writer-population generalization, and no simultaneous familywise claim is made
for every reported secondary comparison.

Attribution enumerates all 16 original action sequences at the same depth and
noise. A truth-aware selector maximizes each original generator's actual
delivered utility before computing CE. This is a stronger search family than
its four deployed plans and has privileged information and extra search cost.
The updated generator exceeds this finite oracle on all three fixed seeds and
on the paired interval. That establishes a generator-family improvement in
this experiment, rather than only learning a better selector for the original
two-step action family. It says nothing about alternative noise search, longer
rollouts, new original-generator actions, or a global multimodal optimum.
