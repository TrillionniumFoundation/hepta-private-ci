# Do the better external probabilities also rank emotions better?

This is a descriptive follow-up to the already examined six-emotion panel. It fits no calibrator and changes no externally predicted probability. For each held actor, calculate the six one-vs-rest AUROCs on that actor's 44 clips, with half credit for ties, and average across emotions. Average actors equally and pair model seeds when comparing arms. This measures within-person discrimination while controlling for actor composition. Also compute the proper multiclass Brier score and mean confidence minus accuracy. Intervals resample 24 actors 4,000 times, holding the three training seeds fixed.

At the one-pass source checkpoint exact HCSN had mean within-actor macro AUROC 0.67033, compared with 0.65950 for causal attention. The paired difference +0.01083 has a 95% interval [−0.00154, +0.02434]. Its Brier difference was −0.01302 [−0.01744, −0.00876]. At the fixed 60-second source checkpoint the exact HCSN had lower Brier by 0.06632 [0.04590, 0.08918], yet its within-actor macro AUROC was 0.65693 compared with 0.68786 for causal attention, a difference of −0.03093 [−0.05113, −0.00933]. Better probabilistic scores in this panel coexist with worse within-actor discrimination at that time budget.

For direct writes against same-site BP, the direct method's within-actor AUROC was 0.57673, and the paired difference was −0.08966 [−0.10600, −0.07287]. Its Brier was higher by 0.10065 [0.09012, 0.11231]. All contrasts use the same 24 actors and previously evaluated model weights. The wide set of subgroup and metric comparisons is exploratory.

[Per-actor values and all contrasts](actor_ranking.json) · [Reproduction program](actor_ranking.py)
