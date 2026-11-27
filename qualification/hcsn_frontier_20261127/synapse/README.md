# Continuous messages predict which observed retinal events coincide with a downstream spike

The primary ten held-out, unique-input repeat segments contain 1,774 measured retinal EPSPs. The prespecified forward matching window assigned a postsynaptic spike to 1,291. The association task differs from predicting an unconditional spike in every time bin. Only input events and input history drive the models.

| Message or control | Held-out balanced log loss | Balanced Brier |
|---|---:|---:|
| Boundary | 0.297727 | 0.087034 |
| Boundary + flow | 0.287570 | 0.085306 |
| Boundary + flow + two prices | 0.282867 | 0.084229 |
| Boundary + seven physical coordinates | 0.281291 | 0.083771 |
| Boundary + seven predictive coordinates | 0.280959 | 0.083721 |
| Boundary + twelve active masses | 0.282191 | 0.083859 |
| Stochastic LIF | 0.284648 | 0.083249 |
| Temporal logistic GLM | 0.376093 | 0.101931 |
| Prevalence | 0.591275 | 0.200509 |

The expanded physical port improves on boundary alone by 0.016436 nats per event (literal expanded minus boundary, paired repeat bootstrap interval [−0.026653, −0.006216]). The corresponding predictive-port gain is 0.016768 [−0.026064, −0.006980]. Equal-width predictive minus physical-horizon is −0.000332 [−0.002214, +0.001302]; this experiment cannot distinguish these two ports. Predictive minus LIF is −0.003689 [−0.010929, +0.002543] and LIF has lower Brier. The synthetic forecast RMSE gain from the independently generated dictionary therefore does not establish a biological prediction gain against either strong control. The full state can express all the features including price channels when the principal is known; the fitted linear classifier, regularization, finite sample, and price–principal interaction can rank encoders differently from their mathematical information content.

See Sincich et al. 2007 (10.1523/JNEUROSCI.5077-06.2007), Carandini et al. 2007 (10.1167/7.14.20), and dataset DOI 10.6080/K0PN93H3. Data are the 76 measured Pre/Post files for odd trials in Challenge_D at InPhyT/Quantitative_Single_Neuron_Modeling_Competition_2009, pinned fdaea54c2fee77e06678d434c7f69ef7093cabb8. These repeats come from the same recording. Time stamps are integer milliseconds; simultaneous bin membership does not identify within-bin causal order. This is an independently held-out subset of the publicly labelled trials; no hidden leaderboard labels were used.

Compile trace.cpp and ../neurons/reservoir.cpp each with g++ -O3 -std=c++17 -shared -fPIC. Run retina.py with --lib /path/to/trace.so --lif /path/to/reservoir.so --data /path/to/Challenge_D --core /path/to/qualification/hcsn_continuous_20261127/core --out /path/to/results under single-thread BLAS. The compressed seal authenticates inputs, choices and coefficients; scores.json identifies the SHA-256 of its original uncompressed JSON. cold.npz contains all event identities, outcomes and probabilities.
