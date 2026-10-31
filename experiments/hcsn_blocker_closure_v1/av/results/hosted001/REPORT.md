# Fresh-actor audiovisual closure study

Valid jobs: 90/90; complete: True.
Passed external contrasts: 1/8.

The population unit is one of eight heldout actors. The analysis resamples paired seeds and actors in a crossed design; clips are not independent actor replicates.

| Budget | Model | Fused accuracy | Audio | Video | Brier | ECE | Whole-worker CPU s |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fixed | value_jg | 0.2969 | 0.3229 | 0.1823 | 0.7999 | 0.1093 | 85.0951 |
| fixed | two_gates | 0.2689 | 0.2754 | 0.1803 | 0.8036 | 0.0450 | 10.6263 |
| fixed | transformer | 0.3392 | 0.3464 | 0.2077 | 0.7877 | 0.0867 | 6.9320 |
| fixed | lif_snn | 0.2155 | 0.2227 | 0.1738 | 0.8250 | 0.0456 | 11.5436 |
| fixed | mamba1 | 0.2174 | 0.2129 | 0.1654 | 0.8234 | 0.0567 | 15.0706 |
| equal_cpu | value_jg | 0.3099 | 0.3294 | 0.1745 | 0.7972 | 0.1016 | 67.7887 |
| equal_cpu | two_gates | 0.2923 | 0.3184 | 0.1947 | 1.2137 | 0.5550 | 71.9069 |
| equal_cpu | transformer | 0.3470 | 0.3581 | 0.2370 | 1.1610 | 0.5475 | 100.3187 |
| equal_cpu | lif_snn | 0.2142 | 0.2598 | 0.1803 | 1.3143 | 0.5911 | 70.8715 |
| equal_cpu | mamba1 | 0.2513 | 0.2695 | 0.1862 | 1.2693 | 0.5808 | 67.2830 |

Raw embeddings, logits, within-actor and whole-pool retrieval ranks, mispairing interventions, checkpoints, failed attempts and cost receipts remain in this attempt. Training CPU is a nested cost; media decoding and registration are separate.

Eight actors and two learning-rate candidates limit the claims. A failed superiority criterion remains a negative result.
