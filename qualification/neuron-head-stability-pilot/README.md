# Historical training-subset stability diagnostic

This is a post-hoc diagnosis inside the previously used 2560-row training pool of #3648, **not a fresh test or qualification**. It neither opens nor scores that experiment's now-exposed1600-row test. Its positive internal result does not replace #3648's inconclusive joint budget hypothesis or #3588/#3593's negative findings.

## Frozen question and actual run

Does the logistic-versus-centroid advantage change consistently across repeated training subsets, rather than depending on one nested draw? A local protocol freeze at2026-10-24T10:25:02Z preceded new subset selection and fitting. Protocol SHA256 e82f399a8c40dfa1b4772d4d31e2e27340f3ade5f377216f26e621730d403ac7. This is not external preregistration.

Rank original training component IDs by a fixed hash:512 internal evaluation rows,2048 sampling-pool rows. Twenty fixed seeds each draw nested320/640/1280 prefixes. Fit60 logistic and60 centroid heads and save every head before scoring the internal evaluation subset. Logistic uses the unchanged200-step float64 Adam/lr0.1/L2 0.001 procedure. No prompt, encoder, feature or optimizer tuning occurs.

The inherited features use per-row native last-token/L2 normalization, not full-pool learned normalization. Every current centroid and weight fit uses only its seed/budget subset. Previously fitted heads are not reused. The source pool and representation are historically exposed, so an internal split does not create a new external evaluation population.

## Results, including zero and negative draws

| Budget | Logistic mean accuracy | Centroid mean accuracy | Mean advantage | Advantage range over20draws |
|---:|---:|---:|---:|---:|
|320|90.8105%|90.1367%|+0.6738pp|[-0.3906,+1.9531]pp|
|640|91.5723%|90.5371%|+1.0352pp|[-0.1953,+1.9531]pp|
|1280|92.1387%|90.6445%|+1.4941pp|[+0.9766,+2.3438]pp|

The sole primary contrast is the seed-mean change in relative advantage from320to1280: **+0.8203pp**, conditional evaluation-source bootstrap95% interval **[+0.3027,+1.3965]pp**. It is a descriptive source-row interval preserving every paired seed/head/budget, conditional on the fixed training pool and draws. It is not a confidence interval from20 independent datasets or a future-generalization guarantee.

Across seeds the relative-advantage change is14 positive,4 zero,2 negative. These are descriptive counts, not independent binomial trials. All60 per-seed budget records and per-evaluation-row correctness frequencies/disagreement rates remain in observed/results.json. No best seed or budget is chosen retrospectively.

Mean advantages grow and their across-draw descriptive standard deviation falls from0.6660pp at320to0.3370pp at1280. This is evidence of improved stability in this fixed historical pool, not a claim that more training always helps or that the2560 endpoint has been independently reproduced.

## Resource and integrity scope

Actual120 head fits:15.24seconds, peakRSS306484KiB (~299.3MiB), twoCPUthreads, noEncoder forwards and no model download. Final logistic gradient norms range1.70e-6…1.16e-4; small gradients do not prove a global optimum or all training stability properties.

Original train tensor/rows/label SHA256 are pinned; run.py indexes only the training NPZ member. split-freeze.json records all subset indices/component identities before fitting. fit-freeze.json binds the full120-head state archive before internal evaluation predictions. Local NPZ head states and raw class predictions are retained for independent numerical review, not published here. No raw news, label arrays, model weights or old1600 test scores are added.

The original executed code is archived under observed/source. It expects the original sibling data layout, not a one-command clean install. replay.py uses NumPy only to check120 recorded accuracies, the primary interval and14/4/2 signs from correctness bits. This is arithmetic evidence replay, not inference or scientific qualification. The user asked to continue local research rather than wait for remote CI; no new dedicated workflow is added and no old remote run is changed.

Independent numerical review passed: the reviewer recomputed the split, all20 nested subsets, all120 prediction arrays/correctness, the primary contrast and10000 bootstrap draws directly from original training features and frozen heads, without opening the old test member or retraining. See observed/independent-review.json.
