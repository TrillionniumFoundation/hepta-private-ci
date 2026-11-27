# Independent T11 cost audit

T11 exited2, selection_ready=false, all actual caps held, formal test unopened. Saved selection and all five build ledgers/costs agree; their SHA256 and frozen identity are bound in JSON. No model/data/test/runtime probe was executed.

| Contribution to NC minus N complete CPU-net utility | Mean |
|---|---:|
| Full-view content gap | -0.001702264094 |
| Same-NC-weight routing | +0.000210519703 |
| Service CPU price | -0.000937209519 |
| Complete build amortization | -0.000208428142 |
| Preparation amortization | +0.000000473962 |
| Reconstructed total | -0.002636908089 |
| Recorded negative contrast | -0.002636908089 |

The identity closes within5e-16. Routing helps in mean but does not offset the content and measured complete-cost losses. All frozen random probabilities are1, so the one-pass random reference is NC always-full.

| Seed | Content | Routing | Complete CPU term | Complete net | N/NC updates | NC decision price |
|---|---:|---:|---:|---:|---|---:|
| 11 | -0.003729633 | -0.000237131 | -0.009488750 | -0.013455514 | 513/488 | 0.002948767423 |
| 23 | +0.000330008 | +0.000044908 | +0.004339805 | +0.004714721 | 514/488 | 0.000000000000 |
| 47 | -0.001707167 | +0.000823781 | +0.001713455 | +0.000830069 | 514/488 | 0.005897534846 |

Seed11 has real measured NC service120,589.690ns/request versus N86,507.857ns; its negative CPU contribution remains intact. Seeds23/47 NC service is faster. Mean N/NC service is96,076.220/99,517.433ns. No outlier or unfavorable seed was removed.

| System | Actual CPU /10s | Units /12B | Unit-stop /CPU-required candidates | Residual rounds |
|---|---:|---:|---|---:|
| additive | 8.678063300 | 11996106665 | 8/1 | 37 |
| anchor | 7.787462691 | 11955587535 | 9/0 | 0 |
| ndu | 8.307966292 | 11958840147 | 9/0 | 0 |
| ndu_control | 8.537556029 | 11901341862 | 9/0 | 0 |
| supervised | 7.611380792 | 11955587535 | 9/0 | 0 |

N/NC each have nine unit-rejected candidate next steps. Their selected updates are513/514/514 versus488/488/488. Neither executes a residual round: N has114,940,269 units but needs168,926,598 for one upper three-seed round+changed-model validation+tail; NC has514,366,155 but needs529,179,051. Deficits are53,986,329 and14,812,896. CPU forecasts remain separately recorded and do not override those required unit reserves.

NativeAdam setup is explicit and symmetric: each arm has9 prepares,65,592 comparisons and65,592 charged units, with P=7,288 parameters. It is reserved before candidate allocation and executed inside billed setup CPU. Allocation, pointer binding, gradient contiguity handling and C dispatch are not subtracted from actual CPU. Per-step mathematical inventories are unchanged, charged once before computation. The adapter persists through selected refinement; shared decoder300/dense500 retain the default optimizer.

Existing mixed-stage rows, logical calls, MAC reductions and actual priced formulas reconcile exactly with ledger deltas and CPU forecast denominators. The conservative envelope is reservation-only and is not charged. The sole readiness failure remains the negative complete CPU-net validation mean; statistical heldout qualification remains unrun.

No action is implied by unused units observed after actual tail costs: the frozen schedule must reserve the required future tail before selecting another update. A bare late update would change the critic/calibration/validation model binding and require their real costs again. The audit makes no new training choice, timing repair or acceptance claim.
