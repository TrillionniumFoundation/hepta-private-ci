# Does the stationary rate improve prediction of measured sweep counts?

Two disjoint specimen cohorts, already collected and scored in the project at d20c92c160c731b320b1426d76481222cbef43a0 under qualification/hcsn_research_20261127/feedback/ephys, supply training-current observations, held-out current levels and baseline predictions. This retrospective comparison preserves their cell-specific splits. It tests an asymptotic firing-rate approximation on finite one-second sweeps; its training count normalization uses one second because the compact files do not give a training duration per current. The two cohorts contain no shared specimen IDs.

| Mean per-cell absolute error, spikes per sweep | Summary-derived cohort | NWB-derived cohort |
|---|---:|---:|
| Cells / held-out current levels | 72 / 174 | 36 / 219 |
| Zero-count held-out levels | 0 | 138 |
| Stationary renewal response | 4.3591 | 1.5563 |
| Original LIF comparator | 4.4440 | 1.802 (rounded) |
| Rectified linear curve | 4.393 | 1.504 |
| Softplus curve | 4.165 | 1.494 |
| Interpolation between neighboring measured currents | 3.717 | 1.331 |
| Original QVI response | 8.241 | 9.018 |

In the NWB cohort the renewal minus LIF difference has a paired-cell interval [−0.438, −0.072] spikes per sweep. On the original summary cohort the analogous interval spans zero [−0.637, +0.526]. Neighbor interpolation yields a lower point error on both cohorts; the difference from the renewal law in the positive-count-only cohort has interval [+0.017,+1.450]. Interpolation benefits from the within-cell design with bracketing currents and cannot extrapolate a new cell. The saturation and threshold shape are capable of fitting actual sweeps without establishing a biological credit mechanism. The exact prices do not enter this three-parameter response; predictive gains from these curves cannot be attributed to financial pricing. The compressed JSON contains all fitted parameters, held-out predictions, archived baseline predictions and paired uncertainty; run allen.py to recreate it from the two specified archives.
