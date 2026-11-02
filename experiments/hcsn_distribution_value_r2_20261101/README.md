# Prospective finite survivor-law and actual-action study

This is a newly designed, identified finite service task after the negative
scalar study in `hcsn_joint_dynamics_20261101`. It does not replace that result or
qualify a learned neural core. The same estimated full law is available to the
strong ordinary uniformization reference and dense marked-CTMC implementation.
Their mathematical agreement is expected and is retained as the primary
analytic-increment comparator.

The adopted protocol is `results/run002/PROTOCOL.json`. Three independently
sampled calibration datasets fit the four context-dependent transition rates,
READ reliability and cue priors. All arms receive identical supervised
identification information. Training has fully observed physical transitions,
state-labelled noisy reads, and balanced/stratified cue-state-target samples.
Test policies receive only the cue, new public context features, prices, action
history, noisy READ bit and outage indicator. They never receive the true test
rates, sampled physical state or target. Hidden path and target fields in raw
records belong to the environment/audit, not the policy interface.

The hidden target bit stays fixed. WAIT advances a real Gillespie path; READ
advances time and obtains a paid noisy observation; RESET preserves the unknown
target, resets physical state and then advances time. STOP submits a bit. Actual
utility uses the realised correct answer, elapsed time, paid actions and repeated
outage count. Exact outage counts are settled after the episode and are not
extra online observations. CPU cost is measured separately, not silently
converted into symbolic utility or device energy.

The main 2×2 is full empirical-distribution ordinary/dense core × rolling-light/
remaining-horizon value controller. Secondary cells independently fit full-joint
or product-marginal cue estimators and separately project the execution belief.
These are finite empirical estimators, not independently trained neural networks.
The mean projection preserves active first moments, target marginal and recovery
mass; the association projection preserves physical and target marginals.

`world.py` owns true parameters and hidden paths. `model.py` owns shared fitted
parameters, two numerical propagators and the explicit projection interventions.
`controller.py` accepts only the estimated candidate and public context/prices.
`campaign.py` freezes, prepares candidates and executes actual trajectories;
`analysis.py` reports all main contrasts and the conditional mechanism witness.

From the repository root, with NumPy/SciPy and one BLAS thread:

```sh
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python -m experiments.hcsn_distribution_value_r2_20261101.campaign freeze --out /tmp/r2-new
python -m experiments.hcsn_distribution_value_r2_20261101.campaign prepare --out /tmp/r2-new
# Publish/read back source, PROTOCOL and ALL_CANDIDATES before opening test.
python -m experiments.hcsn_distribution_value_r2_20261101.campaign confirm --out /tmp/r2-new
```

Use `hcsn_four_stage_flow_20261031.meter` around each phase to include imports,
preparation, planning, every executed alternative and output writes. Inner model
and cell timers are nested inside those outer envelopes. The existing saved
outputs refuse overwrite.

Run001/source and its candidates plus a separate development probe are retained.
Independent review before test widened actual outage-count records from uint8
to int64 with explicit overflow rejection; adopted run002 refroze and repeated
preparation. No registered test sample was opened in run001. Both preparations
and the development probe remain in the cost ledger. The DP uses FP64, a stated
tie tolerance and belief memoization; it is a numerical finite-horizon solution.
