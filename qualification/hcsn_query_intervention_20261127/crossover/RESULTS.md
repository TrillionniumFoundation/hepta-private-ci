# Paired real-stimulus response changes in 48 additional Allen specimens

The registered primary comparison failed. At the same phase of the Noise 2 stimulus, the moving He–Xiong wall predicts the increase in first-hit rate between medium and high amplitudes slightly better than the fixed wall and slightly worse than its matched tangent. A strong supervised boosted current predictor has lower contrast MSE and lower high-amplitude Brier. All physical augmentations have the same fitted readout dimension and receive the same true stationary equity and first-hit population summaries.

The readouts were frozen in e3ee78b17240cba0c676bc13a3a35c62d9dc76e8 before testing. The 18 train and 6 validation donors contributed only the low and medium amplitudes of Noise 1 at 2, 8 and 16 ms. Testing used 48 independently ranked new specimens, 192 recorded sweeps, and 2,111,246,712 raw NWB bytes. Two repetitions used exactly equal imposed current in each of the 96 donor–waveform pairs. The high/low RMS ratio ranged from 2.99961 to 3.00009. Spike outcomes varied across repeats. At each matched phase and 4 or 12 ms horizon, both observed and predicted probabilities were averaged over two trials and three 1-second cycles. The independent recount reconstructed 781,056 binary query targets. The maximum per-donor contrast-score discrepancy was 1.92e−9; high- and medium-dose per-donor NLL/Brier reproduce exactly.

| Sender | High-minus-medium Noise 2 response MSE | High Noise 2 NLL | High Noise 2 Brier | Moving minus sender MSE, paired donor 95% CI |
|---|---:|---:|---:|---|
|Shared smooth current features|.066183|.406198|.122422|+.0002261 [+.0001435,+.0003029]|
|Shared + actual mean E,F|.066230|.406349|.122481|+.0001789 [+.0001058,+.0002492]|
|Shared + E,F + fixed query|.066425|.406213|.122681|−.0000165 [−.0000197,−.0000126]|
|Shared + E,F + tangent query|.066392|.406111|.122642|+.0000170 [+.0000128,+.0000206]|
|Shared + E,F + step-held literal query|.066401|.406140|.122653|+.0000083 [+.0000064,+.0000099]|
|Shared + E,F + moving literal query|.066409|.406162|.122661|reference|
|Boosted current features|.062231|.416853|.119780|+.0041782 [+.0005540,+.0072853]|

The measured average dose-associated probability increase was .081536. The moving-literal readout extrapolated .175195 and the boosted readout .096839. The split-repeat noise term was .013136; subtracting it gives .053273 vs .049095 squared contrast error for these two models. The correction assumes exchangeable independent repeat noise. For the secondary waveform contrast at high amplitude, moving-literal yielded .076452 MSE, shared smooth .076570 and boosting .081507. This distinction matters: relative rankings depend on whether the request is a dose change or a change of waveform. Because the original three dose episodes appear in ascending order, causal attribution of their full difference to instantaneous amplitude would also require controlling adaptation and time order.

The sender's physical features include the active population's mean He–Xiong equity evaluated at its reserve atoms, present first-hit mass and requested probability of a future event. Refractory mass contributes zero to the two present readouts. The stationary equity lookup uses 81 bounded-drive knots; the population uses 12 active bins. All readouts transmitted one FP32 per query. Input-only projected features across the 48 test donors took 568 summed per-specimen seconds in this shared environment, prior to scoring. This is not an end-to-end inference or energy comparison.

The numbered source archives contain all compact raw currents and events with SHA-256 NWB and exact sweep IDs. Each published prediction array covers 3 amplitudes × 3 cycles × 226 phases × 2 horizons. Equal inputs across repetitions allow one copy of the equal FP32 predictions, with independent outcomes retained for both trials. Recount from extracted predictions and source directories using recount.py. results.json contains all donor-level contrasts, the measured pulse ratios, uncertainty and model-comparison directions.
