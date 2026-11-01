# Development mechanisms in the actual finite model

These results use the declared `true_model`, development seed `311000`, and the
fixed specification in `SPEC.json`. No formal fitted checkpoint or confirmation
outcome was read by these scripts. They are constructed and development evidence,
not independent task-gain confirmation. The original root/theory/control sources
were not modified. All results retain their original source hashes.

## 1. Preserved marginals can conceal decision information

The factorization search covers 1,064 constructed joint laws at three intervals:
3,192 comparisons in total. Replacing the joint law by the product of its content
and phase marginals preserves both complete marginals, hence also content and
distance means. Nevertheless, 52 comparisons change the selected action with
positive full-model one-decision regret. Maximum regret is `0.0111856303380784`.

The largest witness assigns probability `0.9` to content 0 at distance `0.05` and
`0.1` to content 1 at distance `0.65`; the distance mean is `0.11`. Factorization
retains these marginals but erases their association. At interval `0.15`:

| Action | Full joint-law Q | Factorized-law Q |
|---|---:|---:|
| ANSWER 0 | 0.9028047786 | 0.9028047786 |
| ANSWER 1 | 0.1028047786 | 0.1028047786 |
| WAIT | 0.8982420044 | 0.8991405653 |
| READ | 0.9139904090 | 0.8845070889 |

The full law selects READ; factorization selects ANSWER 0. The regret is evaluated
using the original full-law Q and optimal subsequent continuation. It is not an
entire projected-policy episode regret. The laws are valid constructed states;
their reachability from the experimental prior and sensor is not established.

The separate mean-compression search starts with 588 independent content/phase
laws and replaces the distance distribution by a two-adjacent-site distribution
with the same mean. Across 1,764 comparisons, **no action changes were found**.
This negative result is retained. It does not prove that a mean is sufficient in
general; it supplies no positive action witness for this particular catalogue.

## 2. Finance and recovery interventions in actual episodes

All variants execute the same 128 paired development episodes. The actual world,
payoffs, read charges, and hidden dynamics remain the true model. Only the
candidate used by the generic HMM filter/common planner changes. A constant read
price is fixed at the initial-prior mean `0.03347560923540505`. Recovery variants
change the candidate generator's recovery mean; the actual mean stays `0.35`.

| Candidate | Changed episode histories | Available reads | Unavailable reads | Realized mean utility | Difference from full |
|---|---:|---:|---:|---:|---:|
| Full model | 0 | 165 | 18 | 0.8376402179 | 0 |
| Zero equity bonus in planner | 0 | 165 | 18 | 0.8376402179 | 0 |
| Constant read price in planner | 9 | 173 | 19 | 0.8499537490 | +0.0123135311 |
| Recovery mean 0.05 in candidate | 10 | 173 | 19 | 0.8577662490 | +0.0201260311 |
| Recovery mean 1.0 in candidate | 1 | 165 | 18 | 0.8454527179 | +0.0078125000 |

These single-seed utility differences are not estimates with validated coverage.
In particular, apparent improvement under a wrong recovery model must not be
interpreted as evidence that the wrong model is better calibrated. Removing the
equity bonus has no observed action or utility effect here; an exported financial
quantity is not automatically a useful decision channel.

### Exact policy expectation separates sampling variation

`policy_expectations.py` enumerates the observation tree while carrying separate
true and candidate beliefs. Actions use only the candidate belief; rewards and
observation probabilities use the actual model. No samples or new dataset are
generated. The full-model policy matches the common planner's exact value.
With uniform weight on the three announced intervals, full expected utility is
`0.8421850023444027`.

| Candidate | Exact true-model expected utility difference |
|---|---:|
| Zero equity bonus | 0 |
| Constant read price | -0.0000565943416065 |
| Recovery mean 0.05 | -0.0000565943416065 |
| Recovery mean 1.0 | -0.0003203230088072 |

Thus the positive realized differences above do not establish positive expected
effects, even inside this known finite model. These deterministic expectations
remain conditional on the synthetic model and are not a generalization result.

## 3. Marginalization on causal development beliefs

Six-step causal histories from the true model produce 16 fixed beliefs. Planning
then uses a declared future interval `0.45`, with 32 root-READ observation samples
and 64 repetitions. No latent labels are passed to the planner.

| Diagnostic | Value |
|---|---:|
| Action disagreement with exact marginalization | 0.046875 |
| Pairwise action-rank disagreement | 0.0133463542 |
| Mean full-Q loss of the sampled action | 0.0003763030 |
| Maximum full-Q loss of the sampled action | 0.0164632785 |

The sampler uses exact conditional continuation and samples only the root READ
marginal. It isolates that expectation's numerical variance. These results do not
describe full sampled-DQN training, nor prove that a neural dynamics core improves
task performance. All sampled action values, variances, causal inputs and beliefs
are retained in `DEVELOPMENT_MECHANISMS.json`.

## 4. Original numerical tie behavior is retained

`TIE_DIAGNOSTIC.json` records a repeated observation of the same development
episode 92. The constant-cost candidate finishes with answer values
`[0.5, 0.49999999999999994]` and selects 0. The fast-recovery candidate finishes
with `[0.49999999999999956, 0.5000000000000004]` and selects 1. This accounts for
their additional `1/128` realized utility difference despite identical exact
expected utility. It is floating-point indifference, not a substantive content
advantage. No tie rule was changed after observing this result; a separate
post-confirmation candidate must remain separate from the original evidence.

## Reproduction and provenance

Run `run.py` for constructed projections, actual development episodes, and causal
Monte Carlo comparisons. Run `policy_expectations.py` for deterministic expected
policy values. Both refuse to overwrite their recorded outcomes. `MANIFEST.json`
hashes the complete local mechanism deliverables and records the upstream source
identities used by the original runs. No result here passes a formal gain gate.
