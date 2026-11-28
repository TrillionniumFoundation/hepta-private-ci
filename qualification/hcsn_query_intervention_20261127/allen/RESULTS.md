# Current-only event forecasts in eight held-out Allen neurons

Across Noise 2 in eight unseen specimens, at 4-ms and 12-ms horizons excluded from training, the hazard-plus-literal predictor scored NLL .1688147 and Brier .0478876. The strong smooth hazard alone scored .1688590/.0479006. The literal augmentation's NLL difference was −.0000443, donor-paired 95% [−.0001169,+.0000141], with lower NLL on three of eight donors. A free smooth augmentation had lower NLL (.1687688), and the literal-minus-free difference was +.0000458 [+.0000110,+.0000882]. The registered broad advantage failed.

| Current-only sender | Held Noise 2 NLL | Held Noise 2 Brier |
|---|---:|---:|
|Fixed query|.1742885|.0505381|
|Tangent query|.1737354|.0504867|
|Literal query|.1729550|.0503814|
|Learned nonlinear current hazard|.1688590|.0479006|
|Hazard + free summary|.1687688|.0478914|
|Hazard + fixed query|.1688479|.0478854|
|Hazard + tangent query|.1688367|.0478894|
|Hazard + literal query|.1688147|.0478876|

The positive result is narrow. The literal augmentation reduced NLL versus the fixed augmentation by .0000332 [−.0000712,−.0000043 for literal minus fixed], but had slightly higher Brier (+.0000022). Its improvement against the tangent augmentation was .0000220, interval [−.0000535,+.0000017]. All methods used the known imposed current and no trial voltage history. Training/selection used 12/4 development specimens, and no test donor contributed to those stages. Both waveform families enter development here, whereas the distinct voltage and crossover studies measure never-trained waveform families.

The model archive seal is commit dbe598423b51f0a5bdf2f9ca990c242db9f2b784. The source cohort consists of 24 intracellular patch-clamp specimens in the Allen Cell Types Database (96 sweeps, 911,904 source bins). The experimental control variable is the imposed intracellular current; the measured response is the membrane-voltage crossing. The stage uses version-correct NWB conversion factors. Fitting consumed enough memory to interrupt two direct implementations; disk_fit.py computed the same objectives using feature blocks and checkpoints, and cold scoring ran one donor at a time. All data, validation selection and metrics are retained. The cold artifact reproduces 32 sweeps from 16 literal FP32 prediction matrices because repeated current commands are identical; each sweep retains its distinct outcomes. Recount recreated 1,502,560 individual horizon–anchor event labels over five horizons, checked all eight model streams bit-for-bit, and matched all primary donor NLL/Brier values exactly.
