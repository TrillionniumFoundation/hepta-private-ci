# A second direct construction using within-class centroids and a Fisher projection

This follow-up applied a layer-local class centroid write and a shared Fisher metric to exactly the same six physical read matrices and output projection. The method had access to the pairing labels during training. The three non-BP methods and the seven-matrix BP comparator each trained two prefixes and three seeds. The raw model used the original normalized cosine scorer. A common alternate readout fitted temperature and training-class priors using the protocol fixed before the trial.

| Method | Raw cold NLL | Raw top-1 | Temperature + prior NLL | Temperature + prior top-1 | Median two-prefix charged seconds |
|---|---:|---:|---:|---:|---:|
| Hidden class-centroid writes + Fisher head | 4.27610 | 4.48% | 4.20417 | 4.70% | 7.38 |
| Shuffled hidden labels + Fisher head | 4.27620 | 3.26% | 4.20442 | 4.65% | 6.60 |
| Fisher head only | 4.27411 | 4.17% | 4.20084 | 5.03% | 5.18 |
| Same-site BP | 4.12971 | 3.48% | 4.04662 | 6.18% | 12.04 |

The full direct method differed from same-site BP by +0.14639 nats (95% paired actor interval +0.10775 to +0.18254) on the raw loss and +0.15756 (+0.11551 to +0.19777) after the shared prior and temperature. No direct seed crossed the joint 4.1 development-and-cold threshold. BP crossed in one of three seeds on raw loss and two after calibration. The raw hidden intervention changed predictions but the head-only Fisher variant had lower NLL. In this construction supervised discrimination of hidden states and optimizing the final gallery probabilities are different objectives. The results are an exploratory reuse of the existing cohort. This particular construction did not close the general optimization problem.
