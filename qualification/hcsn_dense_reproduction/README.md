# Fixed near-dense reproduction — new identity, HOLD

The old unpushed v3 source/raw was lost with executor replacement. #6220 retains that loss transparently. This stage is a new reconstruction and execution; none of its files is attributed to a lost run. Source was pushed before each new execution.

Two fixed 1024-interval profiles are retained: near800 uniform to .5 with 224 exponential far intervals to 8, and near960 uniform to .48 with 64 exponential far intervals to 8. Physics is mu=-.12, sigma=.35, delay=.2, q=.15. The initial law is normalized remaining phase U[0,.025], with signed mark -.7. Resets are .32 and offgrid .32725 respectively. Query times are .001/.003/.02/.04/.08/.16, all before a new hit can return after the delay.

The three near800 DDE controls at atol 1e-14/1e-16/1e-18 retain the local negative result: relative first-hit error at .02 is 1.3326977% / 1.3284986% / 1.3281328%. Positive uniformization gives 1.3280769%. Thus the tight DDE approaches the positive CTMC reference; the original spectral/JF discrepancy was not evidence that time integration dominated it.

The fixed near960 worst offgrid DDE at atol 1e-18 gives M=1.745813153784239e-12 at .02, versus positive CTMC 1.7458119698919143e-12 and continuum GL128 1.728783623562308e-12: about .98506% relative error. This exposed, post-failure point is not a new prospective finite-risk gate, a whole-reset-domain result, or permission to tune again.

An independent analytic reference has no core/model imports. Positive erfc adaptive integrals at 80/120 digits and a separate positive density/Fubini integral agree. At reset .32725, the exact-binary-input 120-digit value is 1.728783623562190402466486064112e-12. FP64 GL64/128 relative reference errors are approximately 1.47e-14 / 6.83e-14. Higher quadrature order does not automatically improve FP64 roundoff.

All four DDE RAW.npz/SUMMARY.json files, original stdout/stderr, five mechanism-test output, source snapshot, and independent reference source/raw are retained. Before/after source guards agree. Every uploaded Git blob SHA was compared against the authentic local bytes. The private controlled solver copy differs from published JointModel only in allowing atol down to 1e-18; shared v2 source is unchanged. All published-base files recovered from #6207 match their exact Git blob identities.

New per-run wall costs (including six positive controls/reference calculations and raw output) are 9.754 / 10.216 / 14.129 seconds for near800, and 11.550 seconds for near960, on one shared host with OPENBLAS_NUM_THREADS=OMP_NUM_THREADS=1. These are not neural model throughput, training, hardware energy or end-to-end costs. Independent high-precision reference took 19.104 seconds. Peak RSS and CPU are retained in each receipt.

Poisson bounds cover truncation only, not FP64 roundoff or continuum discretization. Values below the unchanged relative reference floor 1e-12 gain no relative qualification. Upper escape is permanently active and nonreturning. Right-tail coarsening cost has not been re-executed in this stage: old observer metadata reported deterioration, but its raw is lost; this stage cannot inherit that result as retained evidence. The full reset sweep, actual-law value cost, graded gradients, whole filtering/training, matched baselines and full costs remain separate open gates. Original v1/v2 passes and failures remain source-owned.

Draft / HOLD_NO_GO / all_closed=false. No merge, production adoption, default cell or power-saving claim.
