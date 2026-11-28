# Extended exposure

The fixed two-epoch test measures equal exposure at 4,177,254 target presentations per seed. A separate longer-run control uses the same word probabilities, models, optimizer, schedule, official files and full-split scorer, with a new seed 887 and twelve complete epochs per model. Select the minimum complete validation NLL of the twelve epochs and report its full test NLL only. The long arm addresses sensitivity to early training and does not change the primary criterion. No attention or price hyperparameters are fitted on test data. Assign the longer run to HeptaRuntime's ai395 host, CPU fallback after its six cloud candidates were reserved or otherwise occupied. Independent CPU results and hardware are reported separately. The same-source softmax and fixed context restrictions of the primary qualification still apply.

## Terminal result

The original scientific launch on ai395 created the local corpus arrays and exited before training because its existing torch interpreter lacked SciPy. The recovery uses the same source/model and original input hashes with a math/torch scalar normal-CDF fallback; it ran each model once through twelve training epochs. HeptaRuntime's persistent ai395 terminal was dpty-6ccb65e8e926d7476c0ae8b2c969a838944c4d82c3d90b34033fad8ddc45c578, returned terminal state exited, and reported all four worker exit codes as zero. Device was CPU for all four. Each worker presented 25,063,524 training targets and scored 245,568 test targets. Different compute hardware and a new single seed are reported separately from the main three-seed two-epoch comparison.

| Seed 887, 12 complete epochs | Validation-selected epoch | Complete test NLL | Complete test perplexity | Training targets/s |
|---|---:|---:|---:|---:|
| HX | 12 | 5.79080910 | 327.28 | 184,966 |
| SDPA | 11 | 5.75989078 | 317.31 | 140,288 |
| Smooth | 11 | 5.74306808 | 312.02 | 194,222 |
| Hard LIF | 11 | 5.75856389 | 316.89 | 133,043 |

The smooth control still leads, and SDPA now beats HX on NLL. The four native terminal score receipts and weight-file hashes are in results/hx-887.json, results/sdpa-887.json, results/smooth-887.json and results/lif-887.json.
