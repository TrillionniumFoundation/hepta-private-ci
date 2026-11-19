# Cost-aligned r2 training/validation: failed readiness

Source `cff4888775e27f2896561ff1ff0c55498a46cad5`; immutable freeze `independent/frozen-r2-cost-aligned.json`; execution `ef1d68e59a30b5f742ba9393e3ff600c9ac26936`.

Actual command exited **2**. The formal independent test was not constructed or opened. r1 remains sealed.

Validation mean contrasts (not held-out estimates or confidence intervals):

- `additive-anchor:joint_success`: +0.025882409094
- `additive-anchor:task_utility`: +0.024836177168
- `ndu-additive:joint_success`: +0.003561154779
- `ndu-additive:task_utility`: +0.003497700328
- `ndu_control-ndu:cpu_net_utility`: -0.004656442977
- `ndu_control-random:joint_success`: -0.000487203454
- `ndu_control-random:task_utility`: -0.000355697207

Maximum greedy drop: 0.007812500000; all actual CPU/operator caps held. These do not override the failed raw/random and effective CPU-net gates.

Complete build cost and selected content updates:

| System | CPU seconds | Operator units | Updates by seed 11/23/47 | Residual rounds |
|---|---:|---:|---|---:|
| supervised | 8.990412758 | 11994008123 | 406 / 406 / 406 | 10 |
| anchor | 8.987582449 | 11998504695 | 403 / 403 / 355 | 7 |
| additive | 9.817951283 | 11999113275 | 441 / 441 / 441 | 54 |
| ndu | 9.553969894 | 11998022105 | 406 / 406 / 398 | 20 |
| ndu_control | 9.685044303 | 11040738076 | 357 / 366 / 292 | 0 |

All 15 selected models changed encoder and both content heads; adaptation decoder parameters were fixed. See `parameter-updates.json`. NC residual training admitted zero complete rounds under the frozen future-work forecast. That forecast reserved real new calibration/service work; it was not spent padding or a relaxed cap.

The paired TRAIN calibration retained signed CPU deltas. Seeds 11 and 23 had nonpositive medians and decision price zero; seed 47 price was 0.001426242571. These local measurements do not prove system net benefit. At validation the no-critic random baseline could afford full generation with probability one, and control did not beat its raw utility.

The selected v2 NC seed-11 bundle accepted a handmade normalized RGB image plus external instruction, sampled `blue cross right`, produced a real PNG and checkpoint, and exactly replayed after reload. `standalone-smoke.json` retains the cost/provenance evidence; `selection_ready=false` remains explicit. Serving used no labels or observer. This is a single-request prototype smoke, not formal benefit or batch/device qualification.

Next work: diagnose useful common output/runtime cost and controller error with TRAIN/validation evidence only. Any further method change must be committed and frozen before a new build. No test, gate, data split, price or cap may be changed to turn this failure into a pass. Synchronous AV generation, long interactions and production are unrun.
