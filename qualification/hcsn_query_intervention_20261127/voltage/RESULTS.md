# Measured pre-anchor voltage, new donors, new current waveform and new horizons

The literal moving-boundary operator beat its fixed and tangent ablations on mean log loss and Brier in the primary eight new Allen specimens. The intervals include no difference. A learned cubic wall beat the literal form on both mean scores. The boosted classifier gave the best Brier and the worst log loss. The preregistered superiority gate failed.

Train/validation used Noise 1 exclusively, at 2, 8 and 16 ms on 12/4 separate development donors. The frozen seal was published as a0d550f68fa0eddcccaba25a5735f4625dab635d before cold evaluation. Testing used first-spike events at 4 and 12 ms in the remaining eight donors. Every sender saw the actual pre-anchor voltage and past spike/current history and an external known current command. Output was one FP32 per individual query. Eligibility required <-25 mV immediately before the anchor and no measured spike in the preceding 4 ms. All 24 new public NWBs (889,895,404 bytes) have source SHA-256 receipts. The 96 sweeps have actual pre-anchor membrane extrema −80.31 to +52.06 mV. Binned peak currents were 0.9946–0.9990 of documented unbinned peaks.

| Frozen sender | noise 2 NLL | noise 2 Brier | literal − comparator NLL, donor-paired 95% | donors where literal NLL lower |
|---|---:|---:|---|---:|
|Fixed|.061144|.018139|−.001187 [−.002984,.000763]|5/8|
|Tangent|.060672|.018103|−.000716 [−.001917,.000584]|5/8|
|He–Xiong literal|.059956|.017958|reference|—|
|Free cubic|.059857|.017918|+.000099 [−.000032,.000276]|3/8|
|Smooth logistic|.060758|.017853|−.000801 [−.002861,.002004]|6/8|
|Boosted trees|.079724|.016968|−.019767 [−.043697,.002859]|7/8|

The two independent repeat sweeps have identical measured current within each noise family. Across families, the imposed currents differ despite broadly similar waveforms (about .916 Pearson correlation and .321 relative L2 difference), with almost equal standard deviations. Thus the waveform holdout supplies a real but limited shift. It does not establish transfer to arbitrary stimulation. The analysis contains 59,326 primary horizon–anchor observations out of 60,128 candidates, with 1,449 positive reports. An anchor contributes two horizons; confidence intervals resample donors, not individual forecasts. A separate recount rebuilt every label and eligibility decision from the source and recovered all per-donor scores with maximum discrepancy 1.23e−15. Noise 1 secondary results and all comparison directions are in results.json.

Selected analytic fixed/tangent/literal/cubic models use 22/23/23/25 fitted parameters; the logistic control uses 53. Each selected exact-gradient fit converged; preliminary directional derivatives matched finite differences within 6.8e−12. The boosted comparison uses 160 iterations and a maximum of 15 leaves per tree. Because the frozen models differ in structure and optimization, these results are predictive comparisons, not a hardware/energy advantage. For reproducibility SHA-check the numbered source and prediction ZIPs against their manifests, extract each set into its own folder, restore the booster with gzip decompression and run analysis.py and recount.py. The pickle is the published classifier from this experiment.
