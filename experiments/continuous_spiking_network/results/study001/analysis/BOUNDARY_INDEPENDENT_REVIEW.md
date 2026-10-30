# Independent boundary study review

This is a read-only analysis of study001. No training, tuning, policy selection or sealed source was changed.

Completed planned seeds: [4401, 4402, 4403, 4404, 4405].

## Four-arm outcomes

Each entry is the mean of five seed means. Seed-to-seed SD and unadjusted descriptive 95% t intervals are retained in the JSON. The trained actor and trajectories are shared within each seed.

| Split | Arm | Accuracy | Observations | Observation cost | Net utility |
| --- | --- | ---: | ---: | ---: | ---: |
| ID | fixed | 0.828125 | 3.1426 | 0.113830 | 0.714295 |
| ID | direct | 0.860938 | 4.8258 | 0.099545 | 0.761393 |
| ID | value | 0.860547 | 5.1195 | 0.103857 | 0.756689 |
| ID | oracle | 0.861719 | 4.5043 | 0.091910 | 0.769809 |
| OOD | fixed | 0.856250 | 4.0043 | 0.226660 | 0.629590 |
| OOD | direct | 0.826172 | 3.1941 | 0.110332 | 0.715840 |
| OOD | value | 0.838672 | 4.0746 | 0.128012 | 0.710660 |
| OOD | oracle | 0.830469 | 3.4734 | 0.104738 | 0.725730 |

## Paired utility contrasts

The four contrasts were specified after study launch, before inspecting boundary outcome values. They are analysis choices, not a new preregistered pass/fail gate. The 98.75% t intervals apply a Bonferroni adjustment across these four contrasts; five seeds provide limited precision.

| Split | Contrast | Mean difference | Seed SD | 98.75% t interval | Positive seeds |
| --- | --- | ---: | ---: | --- | ---: |
| ID | value_minus_direct | -0.004703 | 0.015108 | [-0.033856, 0.024450] | 3/5 |
| ID | value_minus_fixed | 0.042395 | 0.009858 | [0.023372, 0.061417] | 5/5 |
| OOD | value_minus_direct | -0.005180 | 0.004588 | [-0.014032, 0.003672] | 0/5 |
| OOD | value_minus_fixed | 0.081070 | 0.030511 | [0.022198, 0.139943] | 5/5 |

## All seed-level contrasts

| Seed | ID value−direct | ID value−fixed | OOD value−direct | OOD value−fixed |
| --- | ---: | ---: | ---: | ---: |
| 4401 | 0.008525 | 0.033223 | -0.004121 | 0.044668 |
| 4402 | -0.026699 | 0.030830 | -0.012559 | 0.052930 |
| 4403 | -0.013438 | 0.049209 | -0.006016 | 0.098770 |
| 4404 | 0.007568 | 0.045645 | -0.002676 | 0.114395 |
| 4405 | 0.000527 | 0.053066 | -0.000527 | 0.094590 |

## Execution and mathematical checks

Shard hashes, unique episode IDs, raw Bayesian LLR arithmetic, the first True stop mask entry, class decisions, correctness, paid observation counts and total costs, and reported utility means are independently recomputed. Fixed/direct threshold decisions are reconstructed, with a 1e-6 margin tolerance for float32 roundoff. Actor manifest hashes and recorded exact reload checks are verified.

Independent NumPy/Gauss-Hermite Bellman reference: 8220 sampled prefix decisions, 4 differences within a .001 reference advantage, and 0 differences beyond that margin. This is a numerical cross-check, not a proof of exact continuum optimality.

## Interpretation limits

- Fixed/direct/value share the same selected actor and causal observation/context inputs. Value is model-informed plug-in stopping on learned logits; the actor's future score dynamics need not match Bayesian LLR transitions, so this is not a proved Bellman optimum for that actor.
- Value embeds the known Gaussian generative model. Direct is a four-parameter context threshold trained for 100 updates, and fixed is a single validation-selected threshold. Their structural priors, function classes and optimization/computation budgets differ.
- The separate raw Bayesian DP arm uses exact raw-evidence log odds and has an expected model-based optimality interpretation, subject to grid/quadrature approximation, not per-episode dominance or a pure boundary improvement.
- Every arm must purchase at least one observation. The oracle is constrained accordingly; it is not an upper bound over policies allowed to guess without purchasing any observation.
- Five independent training/data seeds; episodes and prefixes are not independent model replicates.
- The four t intervals are approximate and multiplicity-adjusted; no new success gate is imposed.
- The boundary actor uses AdamW weight decay 1e-4 on all parameters, as specified in its own implementation/documentation; this differs from the classification pipeline's vector/no-weight-decay exclusion. All three learned-score policy arms still share exactly that actor.
- Saved observation costs are task utility, not energy or measured early-cancellation time. The actor is evaluated on all prefixes offline, and shared actor fitting costs must not be repeatedly charged as if the arms had separately trained actors.
- This boundary experiment evaluates stopping on an HCSN actor, not HCSN superiority over other backbones or a solved endogenous natural spiking threshold.

## Calibration and timing

The JSON retains all-prefix binary Brier score, log loss and probability RMSE against the exact Bayesian posterior. These are descriptive diagnostics; prefixes within an episode are correlated. It also retains each run's actor and policy timing receipts. Timing subtotals are nested and must not all be summed. No test-driven calibration was fitted.
