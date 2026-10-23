# Affine r2 training/validation: failed readiness

Source `cf760d04f26a9b28cb0205ff4820f4c5eeb1cd6a`; freeze `independent/frozen-r2-affine.json`; execution `4e1f90244ac2157da73ff3ad75efc7f9ee2c1333`.

Actual exit **2**, all actual complete build caps held, independent formal test unconstructed/unopened, r1 sealed.

Validation mean contrasts, not held-out estimates or confidence intervals:

- `additive-anchor:joint_success`: +0.007230142434
- `additive-anchor:task_utility`: +0.007444862981
- `ndu-additive:joint_success`: +0.012879575053
- `ndu-additive:task_utility`: +0.012054834348
- `ndu_control-ndu:cpu_net_utility`: -0.014405464881
- `ndu_control-random:joint_success`: +0.001971177093
- `ndu_control-random:task_utility`: +0.001883897941

Maximum greedy drop 0.013888888889.

| System | CPU seconds | Operator units | Updates seed 11/23/47 | Residual rounds |
|---|---:|---:|---|---:|
| supervised | 9.719176536 | 10676728527 | 380 / 410 / 393 | 38 |
| anchor | 9.780656434 | 11533325493 | 433 / 420 / 421 | 71 |
| additive | 9.726016192 | 10529546205 | 357 / 341 / 363 | 59 |
| ndu | 9.719259183 | 10138710669 | 350 / 256 / 349 | 53 |
| ndu_control | 9.023492108 | 7556302288 | 164 / 172 / 169 | 0 |

Full-content NC minus NDU utility: -0.017695946641; affine routing improved utility against its own all-full weights for every seed. The large content deficit dominates complete net benefit. No local routing improvement is presented as overall acceptance.

Shared preparation consumed 6.543093432 CPU seconds, including actual compiler CPU 0.916755295. The remaining shared slowdown has not been causally attributed. A TRAIN calibration max prepare time of 136.988070ms was multiplied into eight forecast NC measures; predicted tail was 2.363858s, actual later fit/calibration/selected-service tail about 0.879944s. This was conservative reservation, not falsified spending. Only maxima were saved, so its historical median/outlier frequency is unknown. The complete cost and signed diagnosis are retained.

All selected content parameters changed while adaptation decoder stayed fixed. The actual affine v2 external RGB smoke emitted `blue cross right`, real PNG, checkpoint and exact replay after reload without serving labels. selection_ready=false remains explicit.

Next prospective repair concerns TRAIN preparation cost forecasting only: retain all three raw samples, use fixed median repeated-work estimate plus one observed max-minus-median excess allowance uniformly across systems, preserve actual strict caps and stop on overrun. It does not modify any score, price, gate, data split or affine decision rule. No MLP is selected. Core content/NDU evidence and the stronger dynamic claim remain separate; positive validation means are not independent proof. AV generation, long interactions, device and production work remain unrun.
