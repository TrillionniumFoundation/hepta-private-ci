# External image–caption grounding under a 512-update budget

We trained 9 raw dual encoders on RSICD and froze all 27 checkpoint identities plus the source-selected covariance model in [ed3d670d](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/ed3d670d8961225001626b0f4ebe220a05da7532). Each checkpoint was loaded in a fresh single-thread process. The test galleries contain 964 source photographs and 2,099 independently collected UCM-caption photographs, each with the first author-provided caption. The guide, source hashes, trained model identities and complete timed input checks accompany the scores.

| Mean of both directions, chance 0.5 | Literal | Matched smooth prices | Causal attention | Paired linear CCA |
|---|---:|---:|---:|---:|
| Source official test | .68191 | .68776 | .68108 | .74855 |
| External UCM | .60456 | .60263 | .60256 | .64044 |
| External UCM, 25 lexically close peers | .51314 | .51079 | .51724 | .53828 |

External true pairs were recognizable: shuffled labels reduced literal concordance to .49816; fixing all images or all captions gave .49949 and .50026. Literal minus smooth was +.00193 (caption-cluster 95% interval −.00939 to +.01354), and literal minus attention was +.00200 (−.01216 to +.01801). Against CCA the point difference was −.03588 (−.09089 to +.01457). Both registered superiority requirements were unmet. The confidence intervals resample normalized primary captions, conditional on the two realized galleries and training seeds. On the source test, literal minus smooth was −.00585 (−.01087 to −.00091). Strict per-image retrieval remains difficult in a corpus with 5 human captions per image and highly repetitive scene language; exact and caption-equivalence R@1 are available in the JSON. Lexically filtered negatives are often plausible alternative descriptions, so this endpoint measures specificity of original associations.

At the .60 target all three neural seeds had to succeed. The three external literal values were .61762, .59413 and .60194; smooth and SDPA likewise had a subthreshold seed. Thus there is no external common-quality neural speed multiplier. The single deterministic CCA did exceed the threshold. It took 43.69 seconds including the shared 23.94-second decode/filter/preparation pass, source fitting/selection and a new confirmation process. This starts with the pre-existing matched RSICD RGB cache and includes decoding raw UCM images. Gallery-independent training at 512 updates is not the same as extensive pretraining. The four-atom financial table is supplied with its hash; this particular small-screen comparison reuses its precomputed values.

The primary and hard-negative conditional intervals and controls are tabulated in RESULTS.json and HARD_RESULTS.json. The longer width-96, three-layer, larger-data program began with a separate [registered protocol](scale/PROTOCOL.md).
