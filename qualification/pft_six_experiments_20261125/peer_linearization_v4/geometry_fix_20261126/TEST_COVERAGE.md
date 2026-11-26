# Added numerical geometry coverage

All eight methods are in `test_peer_geometry.py`. Root executed these eight plus the two unchanged tests in `test_peer_equations.py` once: **10/10 passed** on Python `3.14.4` / NumPy `2.5.5`. These are deterministic matrix fixtures and envelope checks; no model or training runs are included.

| New method | Fixture and assertion | What this establishes |
|---|---|---|
| `test_original_small_scale_impossible_moment_is_refused` | Two zero-Gram/zero-energy peers each claim moment `[1e-14,0]`; global ridge `1e-30`. Requires zero-residual-energy refusal. | Rejects the exact parent counterexample that produced a negative squared-error objective. |
| `test_valid_uniform_extreme_scaling_preserves_solution` | Multiply valid `G,b,c,ridge` together by `1`, `1e-250`, and `1e250`. Expected delta is `[0.8,-2/4.25]`; checks rank two, two observations, one ridge application, arrival-order equality, and consistently scaled objectives. | Accepted well-resolved tiny and large problems retain the same known solution and existing metadata. |
| `test_zero_statistics_are_valid_at_extreme_ridge_scales` | `G=b=c=0`, with ridge `0.25`, `1e-250`, and `1e250`. Requires zero delta, rank, and objectives. | Exact zero statistics remain valid across the stated regularization scales. |
| `test_non_psd_geometry_is_refused_at_every_scale` | A negative Gram diagonal is present at joint scales `1`, `1e-250`, and `1e250`. | Scaling cannot make these explicitly non-positive-semidefinite statistics admissible. |
| `test_unresolved_null_range_and_nonconvex_operator_are_refused` | Nonzero moment in a zero Gram coordinate; a negative Gram direction; and an extremely ill-conditioned regularized operator. All are refused. | The implementation distinguishes invalid geometry and numerically unresolved positive definiteness from a usable update. |
| `test_finite_inputs_that_overflow_aggregation_are_refused` | Individually finite entries overflow when peer Gram matrices are summed, when ridge is added, or when residual energies are summed. | Global finite checks cover operations after per-peer validation. |
| `test_cross_block_scale_cannot_hide_impossible_geometry` | Two peers each have `G=-0.5,b=0,c=5e14`; or totals `G=1e15,b=1,c=1e-20`; or totals `G=1e-30,b=100,c=1e30`. | The negative diagonal and both violations of `b²<=Gc` cannot hide behind a dominant block's scale. |
| `test_valid_subnormal_objective_is_refused_instead_of_reported_zero` | Valid totals `G=ridge=2^-1060,b=2^-500,c=2^60`; exact delta `2^559` and total objective `2^58`. Requires an explicit underflow refusal. | The stated conservative numerical policy prevents a valid but unresolvable scaled objective from silently becoming zero. |

The looped scale cases and adversarial subcases are assertions within eight test methods, not additional independent trials or training runs. The suite supports the listed numerical checks only; it is not evidence of model quality, physical-neuron behavior, peer identity, or a general runtime speedup.

