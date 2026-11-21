# Prospective HCSN mechanism campaign: descriptive evidence

Allocation SHA-256: `eb41dab6881067191c0617c7b656b347e10bbca5e47aa3bfe7d9f741bf055d65`. Protocol SHA-256: `47879cce6fa774bd5d294d02f1fc58d824c4dc85750353730925f71c6f827c9f`. Analysis tool SHA-256: `b30155ae773c25d56aa741fb2255945cf556f3dbfc4d0c1ac2a9840065d0108e`.

All contrasts follow the predeclared plan. Seeds, rather than windows, are the independent reporting units. No p-values, pooled cross-task MSE or large-model superiority claim is produced.

Expected grid: 213 fit method-cases and 417 final method-cells. Complete campaign: **True**.

## Admission and decisions

| Study | Fit valid/admitted/expected | Final valid/admitted/expected | Fit decisions | Issues |
|---|---:|---:|---|---:|
| readout | 48/48/48 | 96/96/96 | {"no_update": 2, "selected": 46} | 0 |
| joint | 48/48/48 | 96/96/96 | {"no_update": 34, "reference": 12, "selected": 2} | 0 |
| architecture | 72/72/72 | 144/144/144 | {"no_update": 58, "selected": 14} | 0 |
| feature | 36/36/36 | 72/72/72 | {"selected": 36} | 0 |
| boundary | 9/9/9 | 9/9/9 | {"reference": 3, "selected": 6} | 0 |

NoUpdate counts are fit decisions, counted once even when the selected incumbent has two final clock scores. UNAVAILABLE and failed cells remain in the expected denominator, but never become completed-method observations.

## Every final seed metric

Seed order: [1907341, 4812467, 8629119]. Full fit/final rows and failure details are in seed_metrics.csv and report.json.

| Study | Task | Split | Method | Seed metrics | Admitted mean [min, max] | Admitted/3 |
|---|---|---|---|---|---|---:|
| architecture | association | final_clock | causal_transformer | 193.1354; 536.3245; 1386.201 | 705.2202 [193.1354, 1386.201] | 3 |
| architecture | association | final_clock | diagonal_linear_ct_ssm | 273.2396; 273.7474; 14.31248 | 187.0998 [14.31248, 273.7474] | 3 |
| architecture | association | final_clock | gru | 2.473545; 0.3014211; 0.239096 | 1.004687 [0.239096, 2.473545] | 3 |
| architecture | association | final_clock | hcsn_finite | 254.5192; 4.459983; 51.93591 | 103.6384 [4.459983, 254.5192] | 3 |
| architecture | association | final_clock | lif_surrogate | 7.771232; 1.420548; 1.687043 | 3.626274 [1.420548, 7.771232] | 3 |
| architecture | association | final_clock | official_cfc | 0.6215761; 1.750641; 0.2728544 | 0.8816906 [0.2728544, 1.750641] | 3 |
| architecture | association | final_iid | causal_transformer | 0.1235486; 0.1371158; 0.1160551 | 0.1255731 [0.1160551, 0.1371158] | 3 |
| architecture | association | final_iid | diagonal_linear_ct_ssm | 0.06167988; 0.0182771; 0.1231961 | 0.06771769 [0.0182771, 0.1231961] | 3 |
| architecture | association | final_iid | gru | 0.03751642; 0.03823985; 0.006386866 | 0.02738105 [0.006386866, 0.03823985] | 3 |
| architecture | association | final_iid | hcsn_finite | 0.04790177; 0.02391855; 0.03073253 | 0.03418428 [0.02391855, 0.04790177] | 3 |
| architecture | association | final_iid | lif_surrogate | 1.644484; 0.5590458; 0.6768938 | 0.9601413 [0.5590458, 1.644484] | 3 |
| architecture | association | final_iid | official_cfc | 0.07262752; 0.03949518; 0.008258833 | 0.04012718 [0.008258833, 0.07262752] | 3 |
| architecture | asynchronous | final_clock | causal_transformer | 0.4922831; 0.844958; 16.50713 | 5.948124 [0.4922831, 16.50713] | 3 |
| architecture | asynchronous | final_clock | diagonal_linear_ct_ssm | 14.35098; 56.54894; 86.00455 | 52.30149 [14.35098, 86.00455] | 3 |
| architecture | asynchronous | final_clock | gru | 0.3779082; 3.065962; 0.797794 | 1.413888 [0.3779082, 3.065962] | 3 |
| architecture | asynchronous | final_clock | hcsn_finite | 80.81849; 49.64065; 815.235 | 315.2314 [49.64065, 815.235] | 3 |
| architecture | asynchronous | final_clock | lif_surrogate | 0.606241; 2.30119; 0.5983496 | 1.168594 [0.5983496, 2.30119] | 3 |
| architecture | asynchronous | final_clock | official_cfc | 0.6537417; 27.43049; 1.738528 | 9.940921 [0.6537417, 27.43049] | 3 |
| architecture | asynchronous | final_iid | causal_transformer | 0.04376763; 0.02393579; 0.1756988 | 0.08113409 [0.02393579, 0.1756988] | 3 |
| architecture | asynchronous | final_iid | diagonal_linear_ct_ssm | 0.03864236; 0.07404588; 0.05412214 | 0.05560346 [0.03864236, 0.07404588] | 3 |
| architecture | asynchronous | final_iid | gru | 0.01701647; 0.1424687; 0.0583986 | 0.07262791 [0.01701647, 0.1424687] | 3 |
| architecture | asynchronous | final_iid | hcsn_finite | 0.05824537; 2.460579; 0.1728634 | 0.8972292 [0.05824537, 2.460579] | 3 |
| architecture | asynchronous | final_iid | lif_surrogate | 0.345197; 0.5061585; 0.2930827 | 0.3814794 [0.2930827, 0.5061585] | 3 |
| architecture | asynchronous | final_iid | official_cfc | 0.04378281; 0.5929135; 0.24055 | 0.2924154 [0.04378281, 0.5929135] | 3 |
| architecture | burst | final_clock | causal_transformer | 11.62387; 48.99142; 1722.974 | 594.5298 [11.62387, 1722.974] | 3 |
| architecture | burst | final_clock | diagonal_linear_ct_ssm | 399.9477; 2096.478; 333.5784 | 943.3348 [333.5784, 2096.478] | 3 |
| architecture | burst | final_clock | gru | 183.4468; 2.940559; 22.69694 | 69.69477 [2.940559, 183.4468] | 3 |
| architecture | burst | final_clock | hcsn_finite | 334.392; 15.19328; 12079.6 | 4143.061 [15.19328, 12079.6] | 3 |
| architecture | burst | final_clock | lif_surrogate | 8.790209; 22.26105; 0.2825544 | 10.44461 [0.2825544, 22.26105] | 3 |
| architecture | burst | final_clock | official_cfc | 86.5598; 18.41876; 13.13137 | 39.36998 [13.13137, 86.5598] | 3 |
| architecture | burst | final_iid | causal_transformer | 0.02624635; 0.05856378; 0.0502925 | 0.04503421 [0.02624635, 0.05856378] | 3 |
| architecture | burst | final_iid | diagonal_linear_ct_ssm | 0.04098069; 0.05247147; 0.09454426 | 0.06266547 [0.04098069, 0.09454426] | 3 |
| architecture | burst | final_iid | gru | 0.06006258; 0.05684585; 0.07883228 | 0.0652469 [0.05684585, 0.07883228] | 3 |
| architecture | burst | final_iid | hcsn_finite | 0.05395753; 0.05207519; 0.1306601 | 0.0788976 [0.05207519, 0.1306601] | 3 |
| architecture | burst | final_iid | lif_surrogate | 1.616761; 2.894795; 0.1573769 | 1.556311 [0.1573769, 2.894795] | 3 |
| architecture | burst | final_iid | official_cfc | 0.04309237; 0.09463136; 0.07776154 | 0.07182842 [0.04309237, 0.09463136] | 3 |
| architecture | first_passage | final_clock | causal_transformer | 11.68898; 28.48127; 407.636 | 149.2688 [11.68898, 407.636] | 3 |
| architecture | first_passage | final_clock | diagonal_linear_ct_ssm | 44.42538; 81.6422; 27.53773 | 51.20177 [27.53773, 81.6422] | 3 |
| architecture | first_passage | final_clock | gru | 0.6714281; 0.2271271; 1.088576 | 0.662377 [0.2271271, 1.088576] | 3 |
| architecture | first_passage | final_clock | hcsn_finite | 27.08803; 53.13645; 170.8353 | 83.68661 [27.08803, 170.8353] | 3 |
| architecture | first_passage | final_clock | lif_surrogate | 13.86336; 21.95959; 10.19698 | 15.33998 [10.19698, 21.95959] | 3 |
| architecture | first_passage | final_clock | official_cfc | 1.35411; 19.82933; 2.648078 | 7.94384 [1.35411, 19.82933] | 3 |
| architecture | first_passage | final_iid | causal_transformer | 0.118069; 0.02994224; 0.03567144 | 0.06122755 [0.02994224, 0.118069] | 3 |
| architecture | first_passage | final_iid | diagonal_linear_ct_ssm | 0.1010105; 0.04106896; 0.0403872 | 0.06082221 [0.0403872, 0.1010105] | 3 |
| architecture | first_passage | final_iid | gru | 0.03039269; 0.01921405; 0.0227424 | 0.02411638 [0.01921405, 0.03039269] | 3 |
| architecture | first_passage | final_iid | hcsn_finite | 0.0873663; 0.03937015; 0.02272032 | 0.04981892 [0.02272032, 0.0873663] | 3 |
| architecture | first_passage | final_iid | lif_surrogate | 11.01423; 7.453341; 2.291201 | 6.919589 [2.291201, 11.01423] | 3 |
| architecture | first_passage | final_iid | official_cfc | 0.02786872; 0.0231316; 0.009693727 | 0.02023135 [0.009693727, 0.02786872] | 3 |
| boundary | finite_control | final | howard_qvi | 0.5700666; 0.6053084; 0.6364086 | 0.6039279 [0.5700666, 0.6364086] | 3 |
| boundary | finite_control | final | lookup_gate_bp | 0.5544963; 0.588939; 0.6229849 | 0.5888067 [0.5544963, 0.6229849] | 3 |
| boundary | finite_control | final | never_reset | 0.3207167; 0.3664132; 0.3699558 | 0.3523619 [0.3207167, 0.3699558] | 3 |
| feature | association | final_clock | drop_value_risk | 12.59164; 2.93554; 7.900664 | 7.809282 [2.93554, 12.59164] | 3 |
| feature | association | final_clock | ordinary_tanh | 3.068421; 0.7925553; 6.092588 | 3.317855 [0.7925553, 6.092588] | 3 |
| feature | association | final_clock | same_generator | 40.42564; 6.130143; 1.627401 | 16.06106 [1.627401, 40.42564] | 3 |
| feature | association | final_iid | drop_value_risk | 0.007681305; 0.006070184; 0.009083157 | 0.007611549 [0.006070184, 0.009083157] | 3 |
| feature | association | final_iid | ordinary_tanh | 0.004086603; 0.005118835; 0.008341319 | 0.005848919 [0.004086603, 0.008341319] | 3 |
| feature | association | final_iid | same_generator | 0.008353757; 0.00571793; 0.009073704 | 0.00771513 [0.00571793, 0.009073704] | 3 |
| feature | asynchronous | final_clock | drop_value_risk | 493.4389; 409.2143; 15.52013 | 306.0578 [15.52013, 493.4389] | 3 |
| feature | asynchronous | final_clock | ordinary_tanh | 350.5002; 176.5904; 7.393154 | 178.1613 [7.393154, 350.5002] | 3 |
| feature | asynchronous | final_clock | same_generator | 526.9211; 353.1168; 143.7917 | 341.2766 [143.7917, 526.9211] | 3 |
| feature | asynchronous | final_iid | drop_value_risk | 0.1464108; 0.06708273; 0.0802732 | 0.09792223 [0.06708273, 0.1464108] | 3 |
| feature | asynchronous | final_iid | ordinary_tanh | 0.0986859; 0.03711273; 0.06248574 | 0.06609479 [0.03711273, 0.0986859] | 3 |
| feature | asynchronous | final_iid | same_generator | 0.1499721; 0.06676565; 0.09509055 | 0.1039428 [0.06676565, 0.1499721] | 3 |
| feature | burst | final_clock | drop_value_risk | 7.577535; 3.646972; 0.4190977 | 3.881202 [0.4190977, 7.577535] | 3 |
| feature | burst | final_clock | ordinary_tanh | 32.4231; 8.998633; 0.7728987 | 14.06488 [0.7728987, 32.4231] | 3 |
| feature | burst | final_clock | same_generator | 91.73564; 83.63984; 588.9075 | 254.761 [83.63984, 588.9075] | 3 |
| feature | burst | final_iid | drop_value_risk | 0.01850366; 0.02308102; 0.02516698 | 0.02225055 [0.01850366, 0.02516698] | 3 |
| feature | burst | final_iid | ordinary_tanh | 0.0217195; 0.02635153; 0.0231478 | 0.02373961 [0.0217195, 0.02635153] | 3 |
| feature | burst | final_iid | same_generator | 0.02106042; 0.02894209; 0.02821784 | 0.02607345 [0.02106042, 0.02894209] | 3 |
| feature | first_passage | final_clock | drop_value_risk | 11.70272; 6.538593; 3.892313 | 7.377874 [3.892313, 11.70272] | 3 |
| feature | first_passage | final_clock | ordinary_tanh | 16.25633; 2.997661; 3.38295 | 7.545647 [2.997661, 16.25633] | 3 |
| feature | first_passage | final_clock | same_generator | 6.116738; 31.51693; 1.042436 | 12.89204 [1.042436, 31.51693] | 3 |
| feature | first_passage | final_iid | drop_value_risk | 0.08209217; 0.0268572; 0.05695198 | 0.05530045 [0.0268572, 0.08209217] | 3 |
| feature | first_passage | final_iid | ordinary_tanh | 0.06091786; 0.01845003; 0.03654315 | 0.03863701 [0.01845003, 0.06091786] | 3 |
| feature | first_passage | final_iid | same_generator | 0.07634746; 0.03494471; 0.03306174 | 0.04811797 [0.03306174, 0.07634746] | 3 |
| joint | association | final_clock | conditional_direct | 9.668996; 1.572358; 46.53367 | 19.25834 [1.572358, 46.53367] | 3 |
| joint | association | final_clock | joint_bp | 9.668996; 1.572358; 46.53367 | 19.25834 [1.572358, 46.53367] | 3 |
| joint | association | final_clock | program_then_bp | 9.668996; 1.572358; 46.53367 | 19.25834 [1.572358, 46.53367] | 3 |
| joint | association | final_clock | semantic_program | 9.668996; 1.572358; 46.53367 | 19.25834 [1.572358, 46.53367] | 3 |
| joint | association | final_iid | conditional_direct | 0.03429831; 0.02535606; 0.01550503 | 0.02505313 [0.01550503, 0.03429831] | 3 |
| joint | association | final_iid | joint_bp | 0.03429831; 0.02535606; 0.01550503 | 0.02505313 [0.01550503, 0.03429831] | 3 |
| joint | association | final_iid | program_then_bp | 0.03429831; 0.02535606; 0.01550503 | 0.02505313 [0.01550503, 0.03429831] | 3 |
| joint | association | final_iid | semantic_program | 0.03429831; 0.02535606; 0.01550503 | 0.02505313 [0.01550503, 0.03429831] | 3 |
| joint | asynchronous | final_clock | conditional_direct | 71.05808; 176.2432; 515.9524 | 254.4179 [71.05808, 515.9524] | 3 |
| joint | asynchronous | final_clock | joint_bp | 71.05808; 176.2432; 515.9524 | 254.4179 [71.05808, 515.9524] | 3 |
| joint | asynchronous | final_clock | program_then_bp | 71.05808; 176.2432; 515.9524 | 254.4179 [71.05808, 515.9524] | 3 |
| joint | asynchronous | final_clock | semantic_program | 71.05808; 176.2432; 515.9524 | 254.4179 [71.05808, 515.9524] | 3 |
| joint | asynchronous | final_iid | conditional_direct | 0.09484881; 0.1173604; 0.1711696 | 0.1277929 [0.09484881, 0.1711696] | 3 |
| joint | asynchronous | final_iid | joint_bp | 0.09484881; 0.1173604; 0.1711696 | 0.1277929 [0.09484881, 0.1711696] | 3 |
| joint | asynchronous | final_iid | program_then_bp | 0.09484881; 0.1173604; 0.1711696 | 0.1277929 [0.09484881, 0.1711696] | 3 |
| joint | asynchronous | final_iid | semantic_program | 0.09484881; 0.1173604; 0.1711696 | 0.1277929 [0.09484881, 0.1711696] | 3 |
| joint | burst | final_clock | conditional_direct | 284.5999; 200.8969; 3.046317 | 162.8477 [3.046317, 284.5999] | 3 |
| joint | burst | final_clock | joint_bp | 284.5999; 200.8969; 3.046317 | 162.8477 [3.046317, 284.5999] | 3 |
| joint | burst | final_clock | program_then_bp | 284.5999; 200.8969; 3.046317 | 162.8477 [3.046317, 284.5999] | 3 |
| joint | burst | final_clock | semantic_program | 284.5999; 200.8969; 3.046317 | 162.8477 [3.046317, 284.5999] | 3 |
| joint | burst | final_iid | conditional_direct | 0.04077474; 0.1873231; 0.02656553 | 0.08488779 [0.02656553, 0.1873231] | 3 |
| joint | burst | final_iid | joint_bp | 0.04077474; 0.1873231; 0.02656553 | 0.08488779 [0.02656553, 0.1873231] | 3 |
| joint | burst | final_iid | program_then_bp | 0.04077474; 0.1873231; 0.02656553 | 0.08488779 [0.02656553, 0.1873231] | 3 |
| joint | burst | final_iid | semantic_program | 0.04077474; 0.1873231; 0.02656553 | 0.08488779 [0.02656553, 0.1873231] | 3 |
| joint | first_passage | final_clock | conditional_direct | 5.975606; 17.31905; 29.45227 | 17.58231 [5.975606, 29.45227] | 3 |
| joint | first_passage | final_clock | joint_bp | 5.975606; 17.31905; 29.45227 | 17.58231 [5.975606, 29.45227] | 3 |
| joint | first_passage | final_clock | program_then_bp | 0.1600482; 17.31905; 29.45227 | 15.64379 [0.1600482, 29.45227] | 3 |
| joint | first_passage | final_clock | semantic_program | 0.3165003; 17.31905; 29.45227 | 15.69594 [0.3165003, 29.45227] | 3 |
| joint | first_passage | final_iid | conditional_direct | 0.1086685; 0.03703832; 0.03489072 | 0.06019916 [0.03489072, 0.1086685] | 3 |
| joint | first_passage | final_iid | joint_bp | 0.1086685; 0.03703832; 0.03489072 | 0.06019916 [0.03489072, 0.1086685] | 3 |
| joint | first_passage | final_iid | program_then_bp | 0.1033901; 0.03703832; 0.03489072 | 0.05843973 [0.03489072, 0.1033901] | 3 |
| joint | first_passage | final_iid | semantic_program | 0.1428109; 0.03703832; 0.03489072 | 0.07157999 [0.03489072, 0.1428109] | 3 |
| readout | association | final_clock | direct | 10.54767; 82.67068; 22.06982 | 38.42939 [10.54767, 82.67068] | 3 |
| readout | association | final_clock | local_bp | 1.965819; 2.18137; 1.635925 | 1.927705 [1.635925, 2.18137] | 3 |
| readout | association | final_clock | program_then_bp | 1.98231; 2.434963; 1.619831 | 2.012368 [1.619831, 2.434963] | 3 |
| readout | association | final_clock | semantic_program | 0.1664528; 0.1443427; 0.1415338 | 0.1507764 [0.1415338, 0.1664528] | 3 |
| readout | association | final_iid | direct | 0.008152425; 0.01949266; 0.006602588 | 0.01141589 [0.006602588, 0.01949266] | 3 |
| readout | association | final_iid | local_bp | 0.007602801; 0.01180757; 0.006197603 | 0.008535991 [0.006197603, 0.01180757] | 3 |
| readout | association | final_iid | program_then_bp | 0.007437374; 0.01138384; 0.006030247 | 0.00828382 [0.006030247, 0.01138384] | 3 |
| readout | association | final_iid | semantic_program | 0.2157154; 0.2181188; 0.1865413 | 0.2067918 [0.1865413, 0.2181188] | 3 |
| readout | asynchronous | final_clock | direct | 58.52621; 168.5375; 77.16351 | 101.4091 [58.52621, 168.5375] | 3 |
| readout | asynchronous | final_clock | local_bp | 14.16858; 23.15506; 12.63593 | 16.65319 [12.63593, 23.15506] | 3 |
| readout | asynchronous | final_clock | program_then_bp | 16.88886; 19.99302; 8.927144 | 15.26967 [8.927144, 19.99302] | 3 |
| readout | asynchronous | final_clock | semantic_program | 0.2755976; 0.219154; 0.2028303 | 0.2325273 [0.2028303, 0.2755976] | 3 |
| readout | asynchronous | final_iid | direct | 0.09321136; 0.08466703; 0.05712353 | 0.07833397 [0.05712353, 0.09321136] | 3 |
| readout | asynchronous | final_iid | local_bp | 0.06033046; 0.07607341; 0.06188625 | 0.06609671 [0.06033046, 0.07607341] | 3 |
| readout | asynchronous | final_iid | program_then_bp | 0.05919666; 0.07692723; 0.05613584 | 0.06408658 [0.05613584, 0.07692723] | 3 |
| readout | asynchronous | final_iid | semantic_program | 0.2367377; 0.2279056; 0.2245568 | 0.2297334 [0.2245568, 0.2367377] | 3 |
| readout | burst | final_clock | direct | 51.97195; 198.6245; 103.1946 | 117.9303 [51.97195, 198.6245] | 3 |
| readout | burst | final_clock | local_bp | 1.685462; 1.797375; 0.763028 | 1.415288 [0.763028, 1.797375] | 3 |
| readout | burst | final_clock | program_then_bp | 1.612608; 1.80142; 2.606011 | 2.00668 [1.612608, 2.606011] | 3 |
| readout | burst | final_clock | semantic_program | 0.04075195; 0.06065738; 0.03564389 | 0.04568441 [0.03564389, 0.06065738] | 3 |
| readout | burst | final_iid | direct | 0.04444624; 0.03547132; 0.06789129 | 0.04926962 [0.03547132, 0.06789129] | 3 |
| readout | burst | final_iid | local_bp | 0.02624056; 0.01971583; 0.02036351 | 0.02210663 [0.01971583, 0.02624056] | 3 |
| readout | burst | final_iid | program_then_bp | 0.02364708; 0.02004632; 0.02131286 | 0.02166875 [0.02004632, 0.02364708] | 3 |
| readout | burst | final_iid | semantic_program | 0.02046436; 0.02215061; 0.02622841 | 0.0229478 [0.02046436, 0.02622841] | 3 |
| readout | first_passage | final_clock | direct | 68.3482; 22.27729; 7.42794 | 32.68448 [7.42794, 68.3482] | 3 |
| readout | first_passage | final_clock | local_bp | 1.771192; 1.235604; 4.859699 | 2.622165 [1.235604, 4.859699] | 3 |
| readout | first_passage | final_clock | program_then_bp | 1.530575; 0.9438554; 4.038416 | 2.170949 [0.9438554, 4.038416] | 3 |
| readout | first_passage | final_clock | semantic_program | 0.3583465; 0.3721907; 0.1709689 | 0.300502 [0.1709689, 0.3721907] | 3 |
| readout | first_passage | final_iid | direct | 0.02980471; 0.02270302; 0.0319107 | 0.02813948 [0.02270302, 0.0319107] | 3 |
| readout | first_passage | final_iid | local_bp | 0.02503834; 0.02895406; 0.02501931 | 0.02633724 [0.02501931, 0.02895406] | 3 |
| readout | first_passage | final_iid | program_then_bp | 0.02534695; 0.02852259; 0.02510703 | 0.02632553 [0.02510703, 0.02852259] | 3 |
| readout | first_passage | final_iid | semantic_program | 0.1367141; 0.1804947; 0.2096053 | 0.1756047 [0.1367141, 0.2096053] | 3 |

## Predeclared paired differences

Differences are left minus right. H1/H3 prefer smaller MSE; H2 prefers higher full expected return. H3 tolerance is max(1e-6, 0.01 × incumbent development MSE), separately for each seed. An all-three pattern is descriptive.

| Hypothesis | Task | Split | Left − right | Paired seed differences | Admitted/3 | H3 screen |
|---|---|---|---|---|---:|---|
| H1 (feature) | association | final_clock | same_generator − ordinary_tanh | 37.35722; 5.337588; -4.465187 | 3 | — |
| H1 (feature) | association | final_iid | same_generator − ordinary_tanh | 0.004267154; 0.0005990959; 0.0007323849 | 3 | — |
| H1 (feature) | asynchronous | final_clock | same_generator − ordinary_tanh | 176.4209; 176.5264; 136.3986 | 3 | — |
| H1 (feature) | asynchronous | final_iid | same_generator − ordinary_tanh | 0.05128616; 0.02965293; 0.03260481 | 3 | — |
| H1 (feature) | burst | final_clock | same_generator − ordinary_tanh | 59.31254; 74.64121; 588.1346 | 3 | — |
| H1 (feature) | burst | final_iid | same_generator − ordinary_tanh | -0.0006590797; 0.002590556; 0.005070043 | 3 | — |
| H1 (feature) | first_passage | final_clock | same_generator − ordinary_tanh | -10.13959; 28.51927; -2.340513 | 3 | — |
| H1 (feature) | first_passage | final_iid | same_generator − ordinary_tanh | 0.0154296; 0.01649468; -0.003481408 | 3 | — |
| H1_diagnostic (feature) | association | final_clock | same_generator − drop_value_risk | 27.834; 3.194603; -6.273263 | 3 | — |
| H1_diagnostic (feature) | association | final_iid | same_generator − drop_value_risk | 0.0006724517; -0.0003522532; -9.453328e-06 | 3 | — |
| H1_diagnostic (feature) | asynchronous | final_clock | same_generator − drop_value_risk | 33.48226; -56.09754; 128.2716 | 3 | — |
| H1_diagnostic (feature) | asynchronous | final_iid | same_generator − drop_value_risk | 0.003561307; -0.0003170727; 0.01481735 | 3 | — |
| H1_diagnostic (feature) | burst | final_clock | same_generator − drop_value_risk | 84.1581; 79.99287; 588.4884 | 3 | — |
| H1_diagnostic (feature) | burst | final_iid | same_generator − drop_value_risk | 0.002556766; 0.005861066; 0.003050861 | 3 | — |
| H1_diagnostic (feature) | first_passage | final_clock | same_generator − drop_value_risk | -5.585978; 24.97834; -2.849877 | 3 | — |
| H1_diagnostic (feature) | first_passage | final_iid | same_generator − drop_value_risk | -0.005744711; 0.008087514; -0.02389024 | 3 | — |
| H2 (boundary) | finite_control | final | howard_qvi − lookup_gate_bp | 0.01557033; 0.01636945; 0.0134237 | 3 | — |
| H2_reference (boundary) | finite_control | final | howard_qvi − never_reset | 0.24935; 0.2388953; 0.2664528 | 3 | — |
| H2_reference (boundary) | finite_control | final | lookup_gate_bp − never_reset | 0.2337796; 0.2225258; 0.2530291 | 3 | — |
| H3 (readout) | association | final_clock | direct − local_bp | 8.581854 (τ=0.002498252); 80.48931 (τ=0.001980719); 20.4339 (τ=0.002947845) | 3 | does_not_meet |
| H3 (readout) | association | final_iid | direct − local_bp | 0.0005496241 (τ=0.002498252); 0.007685087 (τ=0.001980719); 0.000404985 (τ=0.002947845) | 3 | does_not_meet |
| H3 (readout) | asynchronous | final_clock | direct − local_bp | 44.35763 (τ=0.004275292); 145.3825 (τ=0.005243589); 64.52758 (τ=0.005857074) | 3 | does_not_meet |
| H3 (readout) | asynchronous | final_iid | direct − local_bp | 0.03288089 (τ=0.004275292); 0.008593612 (τ=0.005243589); -0.004762718 (τ=0.005857074) | 3 | does_not_meet |
| H3 (readout) | burst | final_clock | direct − local_bp | 50.28648 (τ=0.003283413); 196.8271 (τ=0.004060388); 102.4316 (τ=0.003128018) | 3 | does_not_meet |
| H3 (readout) | burst | final_iid | direct − local_bp | 0.01820568 (τ=0.003283413); 0.0157555 (τ=0.004060388); 0.04752778 (τ=0.003128018) | 3 | does_not_meet |
| H3 (readout) | first_passage | final_clock | direct − local_bp | 66.57701 (τ=0.001790192); 21.04168 (τ=0.0009225397); 2.56824 (τ=0.0006109427) | 3 | does_not_meet |
| H3 (readout) | first_passage | final_iid | direct − local_bp | 0.004766377 (τ=0.001790192); -0.006251038 (τ=0.0009225397); 0.006891391 (τ=0.0006109427) | 3 | does_not_meet |
| H3 (readout) | association | final_clock | semantic_program − local_bp | -1.799366 (τ=0.002498252); -2.037028 (τ=0.001980719); -1.494391 (τ=0.002947845) | 3 | meets |
| H3 (readout) | association | final_iid | semantic_program − local_bp | 0.2081126 (τ=0.002498252); 0.2063112 (τ=0.001980719); 0.1803437 (τ=0.002947845) | 3 | does_not_meet |
| H3 (readout) | asynchronous | final_clock | semantic_program − local_bp | -13.89298 (τ=0.004275292); -22.9359 (τ=0.005243589); -12.4331 (τ=0.005857074) | 3 | meets |
| H3 (readout) | asynchronous | final_iid | semantic_program − local_bp | 0.1764072 (τ=0.004275292); 0.1518322 (τ=0.005243589); 0.1626705 (τ=0.005857074) | 3 | does_not_meet |
| H3 (readout) | burst | final_clock | semantic_program − local_bp | -1.64471 (τ=0.003283413); -1.736718 (τ=0.004060388); -0.7273841 (τ=0.003128018) | 3 | meets |
| H3 (readout) | burst | final_iid | semantic_program − local_bp | -0.005776204 (τ=0.003283413); 0.002434784 (τ=0.004060388); 0.005864903 (τ=0.003128018) | 3 | does_not_meet |
| H3 (readout) | first_passage | final_clock | semantic_program − local_bp | -1.412846 (τ=0.001790192); -0.8634133 (τ=0.0009225397); -4.688731 (τ=0.0006109427) | 3 | meets |
| H3 (readout) | first_passage | final_iid | semantic_program − local_bp | 0.1116758 (τ=0.001790192); 0.1515407 (τ=0.0009225397); 0.184586 (τ=0.0006109427) | 3 | does_not_meet |
| H3 (readout) | association | final_clock | program_then_bp − local_bp | 0.01649094 (τ=0.002498252); 0.2535929 (τ=0.001980719); -0.01609434 (τ=0.002947845) | 3 | does_not_meet |
| H3 (readout) | association | final_iid | program_then_bp − local_bp | -0.0001654266 (τ=0.002498252); -0.0004237282 (τ=0.001980719); -0.0001673557 (τ=0.002947845) | 3 | meets |
| H3 (readout) | asynchronous | final_clock | program_then_bp − local_bp | 2.720279 (τ=0.004275292); -3.162037 (τ=0.005243589); -3.708784 (τ=0.005857074) | 3 | does_not_meet |
| H3 (readout) | asynchronous | final_iid | program_then_bp − local_bp | -0.001133807 (τ=0.004275292); 0.0008538214 (τ=0.005243589); -0.005750406 (τ=0.005857074) | 3 | meets |
| H3 (readout) | burst | final_clock | program_then_bp − local_bp | -0.07285365 (τ=0.003283413); 0.004044849 (τ=0.004060388); 1.842983 (τ=0.003128018) | 3 | does_not_meet |
| H3 (readout) | burst | final_iid | program_then_bp − local_bp | -0.00259348 (τ=0.003283413); 0.0003304868 (τ=0.004060388); 0.0009493484 (τ=0.003128018) | 3 | meets |
| H3 (readout) | first_passage | final_clock | program_then_bp − local_bp | -0.240617 (τ=0.001790192); -0.2917485 (τ=0.0009225397); -0.8212832 (τ=0.0006109427) | 3 | meets |
| H3 (readout) | first_passage | final_iid | program_then_bp − local_bp | 0.0003086131 (τ=0.001790192); -0.0004314689 (τ=0.0009225397); 8.772033e-05 (τ=0.0006109427) | 3 | meets |
| H3 (joint) | association | final_clock | conditional_direct − joint_bp | 0 (τ=8.910604e-05); 0 (τ=0.0001062515); 0 (τ=0.0002900169) | 3 | meets |
| H3 (joint) | association | final_iid | conditional_direct − joint_bp | 0 (τ=8.910604e-05); 0 (τ=0.0001062515); 0 (τ=0.0002900169) | 3 | meets |
| H3 (joint) | asynchronous | final_clock | conditional_direct − joint_bp | 0 (τ=0.0008754147); 0 (τ=0.0008433404); 0 (τ=0.001761004) | 3 | meets |
| H3 (joint) | asynchronous | final_iid | conditional_direct − joint_bp | 0 (τ=0.0008754147); 0 (τ=0.0008433404); 0 (τ=0.001761004) | 3 | meets |
| H3 (joint) | burst | final_clock | conditional_direct − joint_bp | 0 (τ=0.0005214716); 0 (τ=0.0002362972); 0 (τ=0.0001669864) | 3 | meets |
| H3 (joint) | burst | final_iid | conditional_direct − joint_bp | 0 (τ=0.0005214716); 0 (τ=0.0002362972); 0 (τ=0.0001669864) | 3 | meets |
| H3 (joint) | first_passage | final_clock | conditional_direct − joint_bp | 0 (τ=0.0009804908); 0 (τ=0.000315169); 0 (τ=0.0002696571) | 3 | meets |
| H3 (joint) | first_passage | final_iid | conditional_direct − joint_bp | 0 (τ=0.0009804908); 0 (τ=0.000315169); 0 (τ=0.0002696571) | 3 | meets |
| H3 (joint) | association | final_clock | semantic_program − joint_bp | 0 (τ=8.910604e-05); 0 (τ=0.0001062515); 0 (τ=0.0002900169) | 3 | meets |
| H3 (joint) | association | final_iid | semantic_program − joint_bp | 0 (τ=8.910604e-05); 0 (τ=0.0001062515); 0 (τ=0.0002900169) | 3 | meets |
| H3 (joint) | asynchronous | final_clock | semantic_program − joint_bp | 0 (τ=0.0008754147); 0 (τ=0.0008433404); 0 (τ=0.001761004) | 3 | meets |
| H3 (joint) | asynchronous | final_iid | semantic_program − joint_bp | 0 (τ=0.0008754147); 0 (τ=0.0008433404); 0 (τ=0.001761004) | 3 | meets |
| H3 (joint) | burst | final_clock | semantic_program − joint_bp | 0 (τ=0.0005214716); 0 (τ=0.0002362972); 0 (τ=0.0001669864) | 3 | meets |
| H3 (joint) | burst | final_iid | semantic_program − joint_bp | 0 (τ=0.0005214716); 0 (τ=0.0002362972); 0 (τ=0.0001669864) | 3 | meets |
| H3 (joint) | first_passage | final_clock | semantic_program − joint_bp | -5.659106 (τ=0.0009804908); 0 (τ=0.000315169); 0 (τ=0.0002696571) | 3 | meets |
| H3 (joint) | first_passage | final_iid | semantic_program − joint_bp | 0.03414249 (τ=0.0009804908); 0 (τ=0.000315169); 0 (τ=0.0002696571) | 3 | does_not_meet |
| H3 (joint) | association | final_clock | program_then_bp − joint_bp | 0 (τ=8.910604e-05); 0 (τ=0.0001062515); 0 (τ=0.0002900169) | 3 | meets |
| H3 (joint) | association | final_iid | program_then_bp − joint_bp | 0 (τ=8.910604e-05); 0 (τ=0.0001062515); 0 (τ=0.0002900169) | 3 | meets |
| H3 (joint) | asynchronous | final_clock | program_then_bp − joint_bp | 0 (τ=0.0008754147); 0 (τ=0.0008433404); 0 (τ=0.001761004) | 3 | meets |
| H3 (joint) | asynchronous | final_iid | program_then_bp − joint_bp | 0 (τ=0.0008754147); 0 (τ=0.0008433404); 0 (τ=0.001761004) | 3 | meets |
| H3 (joint) | burst | final_clock | program_then_bp − joint_bp | 0 (τ=0.0005214716); 0 (τ=0.0002362972); 0 (τ=0.0001669864) | 3 | meets |
| H3 (joint) | burst | final_iid | program_then_bp − joint_bp | 0 (τ=0.0005214716); 0 (τ=0.0002362972); 0 (τ=0.0001669864) | 3 | meets |
| H3 (joint) | first_passage | final_clock | program_then_bp − joint_bp | -5.815558 (τ=0.0009804908); 0 (τ=0.000315169); 0 (τ=0.0002696571) | 3 | meets |
| H3 (joint) | first_passage | final_iid | program_then_bp − joint_bp | -0.005278305 (τ=0.0009804908); 0 (τ=0.000315169); 0 (τ=0.0002696571) | 3 | meets |

## Measured cost and failures

```json
{
  "observed_fit_final_child_seconds": 77.27324711508118,
  "expected_fit_final_ceiling_seconds": 810,
  "complete_fit_final_child_seconds": 77.27324711508118,
  "observed_freeze_child_seconds_separate": 10.417943236068822,
  "registration_setup_seconds_by_plan": {
    "eb41dab6881067191c0617c7b656b347e10bbca5e47aa3bfe7d9f741bf055d65": 0.19658125599380583
  },
  "unknown_process_phases": [],
  "program_design_cost": "unknown; cannot be treated as zero",
  "scope": "sum each complete fit/final subprocess once; ledger snapshots and per-arm lower bounds are not added"
}
```

Per-arm standalone lower bounds include declared common setup; actual shared work is charged once. Unknown program design, assistant tokens, API charges and missing process intervals prevent a complete adaptation-time claim. The boundary experiment uses known dynamics; its stochastic-gate clock differs from hard instantaneous intervention. The architecture experiment covers one small parameter band, not multimodal foundation-model scaling.

### readout unresolved issues

None reported by this read-only evidence audit.

### joint unresolved issues

None reported by this read-only evidence audit.

### architecture unresolved issues

None reported by this read-only evidence audit.

### feature unresolved issues

None reported by this read-only evidence audit.

### boundary unresolved issues

None reported by this read-only evidence audit.

## Allocation issues

None.