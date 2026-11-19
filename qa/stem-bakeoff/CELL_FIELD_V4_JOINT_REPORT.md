# Cell parameter-field V4: joint scientific and execution report

Date: 2026-10-25. Disposition: **REJECT `structured4_h8`; no candidate publication, activation, or production authority.**

The declared candidate passed **1 of 12 scientific criteria** and **0 of 4 CPU criteria**. Its mean future-test NLL was worse than `myopic_full_h1` in all four task/head combinations. Its charged CPU cost was **11.18–13.07 times** the myopic baseline, above the registered limit of 3.0. These are completed negative results, not missing experiments. The separate execution audit passed: all 1,764 fixed H8 branches and all 12 candidate midpoint continuations reproduced exactly. [Evaluation](./evidence/20261025-cell-field-v4/evaluation.json), [scientific disposition](./evidence/20261025-cell-field-v4/scientific-review.json), [replay audit](./evidence/20261025-cell-field-v4/replay-audit.json).

## 1. What the five workstreams established

| Workstream | Completed evidence | Conclusion within this experiment |
|---|---|---|
| P0: same-action field prediction | Five predictors, 36 anchors, 49 fixed actions per anchor, 1,764 executed H8 branches | Full optimizer-state tangent forecasts are substantially more accurate. Using four field coordinates does not ensure good action ranking. |
| P1: causal policy and generalization gate | Seven policies, two task families, two heads, three seeds; 84 complete outputs | The predeclared structured4 candidate fails the joint scientific and measured-cost gate. |
| Retention pressure | All 744 registered slots retained, including infeasible/unresolved plans | Hard constraints change actions, but tangent feasibility frequently fails on the actual nonlinear path; probe rescues do not establish held-out retention. |
| Objective and cost decomposition | Matched direction/amplitude comparisons, risk/forgetting/action-cost breakdowns | The fixed-library objective strongly prefers zero even when some directions improve current risk. Objective pricing and field fidelity are distinct issues. |
| Native admission and replay | Real report and all-12-fit parameter bundles submitted to the native publication gate; complete deterministic replay | The gate rejects the real candidate before owner publication. Integrity success grants no scientific or serving authority. |

The [frozen protocol](./cell_field_joint_protocol_v4.json) was published at [b05a6c823ba7f7651aa5709c2828405e8333b061](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/b05a6c823ba7f7651aa5709c2828405e8333b061) before new encoder/model outcomes. Its SHA256 is `30880ddaae978f622cf6a99cf3888771daa954777e6f9ce2a75c25f01f166280`. This is a local/remote pre-outcome record, not independent preregistration. Research and native changes are separate branches: [dot/cell-field-joint-v4-20261025](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/dot/cell-field-joint-v4-20261025) and [dot/cell-native-scientific-review-v4-20261025](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/dot/cell-native-scientific-review-v4-20261025).

The matching executed implementation was published at [55d078fa1182006a4694aabfa48bbab23de9878a](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/55d078fa1182006a4694aabfa48bbab23de9878a). The local source snapshot was fixed before execution; later audit/report/acquisition tools are identified separately and are not retroactively inserted into that historical closure. [Qualification record](./evidence/20261025-cell-field-v4/qualification.json). The native admission change and actual negative-result driver are reviewable in [draft PR #3879](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3879).

## 2. Experimental object, data, and access boundary

The experiment trains actual Linear36/Gated52 classification heads on frozen Granite 97M embeddings. The frozen encoder emits 384 features; a label-independent Gaussian QR projection reduces them to width 8. Each head predicts four classes. The encoder checkpoint is `835ad14087e140460703cf0fae09f97d469d65c2`; it receives no labels and undergoes no updates. This is an experiment with a frozen text encoder and small Cell heads, not LLM fine-tuning. [Encoder reports](./evidence/20261025-cell-field-v4/features/uci-report.json), [20NG encoder report](./evidence/20261025-cell-field-v4/features/newsgroups-report.json).

| Source role | UCI News Aggregator | Four-category 20 Newsgroups |
|---|---:|---:|
| Old train / controller probe | 64 / 32 | 64 / 32 |
| Old validation / independent old test | 32 / 32 | 64 / 64 |
| Current train / controller probe | 32 / 16 | 64 / 32 |
| Current validation / future test | 32 / 112 | 64 / 128 |
| Total distinct selected source components | 352 | 512 |

The 864 selected rows represent 864 distinct source components. The source audit found no duplicate normalized model inputs; UCI has zero overlap with the registered historical component exclusions. Source selection is class-balanced and the preparer necessarily sees source categories; training, validation, and final labels are then written to separate payloads. Unknown exposure through the public encoder's pretraining is not excluded. [Source audit](./evidence/20261025-cell-field-v4/source-audit.json), [UCI receipt](./evidence/20261025-cell-field-v4/data/uci-receipt.json), [20NG receipt](./evidence/20261025-cell-field-v4/data/newsgroups-receipt.json).

UCI uses April 2014 for old data, May for current data, and July for future data. A source-only feasibility amendment was fixed before encoder/model outcomes: the originally proposed June cohort had zero eligible health components after historical exclusions. Counts and months were changed at that stage, without consulting new model performance. The exact exclusions and class counts remain in the UCI receipt.

20NG uses `comp.graphics`, `rec.autos`, `sci.space`, and `talk.politics.misc`. Old/current subsets are deterministic component-hash partitions of the official training split; the official test split supplies future data. The downloaded archive has no Date or Message-ID headers in the target messages, so **no within-training-set temporal ordering is claimed**. Cleaning removes headers, quoted lines, and signatures; 35 selected messages hit the 6,000-character source cap. The encoder cap is **192 tokens**; 186 of 512 selected 20NG inputs were token-truncated, compared with zero UCI inputs. These are different truncation counts.

The runner admits only old/current training and controller-probe labels. It seals all prediction artifacts before the evaluator opens validation or final labels. The [pre-evaluation seal](./evidence/20261025-cell-field-v4/pre-evaluation-seal.json) and subsequent [label-access receipt](./evidence/20261025-cell-field-v4/label-access.json) record that order. SHA256 inventories establish local integrity and recorded order; they are not signatures or third-party attestations.

## 3. P0: five forecasts of identical physical actions

The complete deterministic optimizer state is theta, first and second Adam moments, and the known clock, with checkpoint bindings and sampler state retained. State dimension is 108 for Linear36 and 156 for Gated52. After 64 old-task warmup updates, fixed anchors occur after 0, 8, and 16 unforced current-task updates. Three seeds are fixed: 7, 17, and 29.

Every predictor receives the same one-step physical intervention: after the first Adam update, add `h*u` to theta with `h=0.02`; take seven subsequent Adam steps with zero interventions. Eight fixed SHA256 sign directions, both polarities, and amplitudes 0.125, 0.5, and 1.0 give 48 nonzero actions plus zero. The coordinate bound is `abs(u_j) <= 1/sqrt(p)`. Directions are neither learned nor reseeded. [Action library](./cell_field_fixed_actions.py), [predictor implementation](./cell_field_dynamics_v4.py).

| Predictor | Retained observation / reconstruction | Additional dependency |
|---|---|---|
| loss2 | Current and old controller-probe losses | Dense reference transition and observation derivatives |
| q4 | Both losses and each probe gradient dotted with raw Adam momentum | The inherited four-coordinate construction |
| history4 | Two losses at each of two consecutive times; transition-consistent delay reconstruction | Known previous action subtraction/reinsertion; an additional p-float action memory |
| structured4 | Both losses and each probe gradient dotted with the next unforced, bias-corrected Adam parameter update | Optimizer-aware directional Jacobians |
| full | Complete scaled theta/m/v tangent, with the original clock | All optimizer-state coordinates |

History4 is not an independent pseudoinverse of two unrelated observations: its reconstruction uses the known transition and preceding action. Structured4 uses fixed scaled theta finite differences of `2e-5` with a half-step audit; moment columns are analytic, avoiding negative-variance perturbations. All compact modes still depend on complete-state preparation. The implementation therefore establishes neither an autonomous small observer nor cheap deployment.

### Same-amplitude results

At amplitude 1.0, each anchor ranks the same 16 nonzero directions. Loss RMSE pools both development-probe losses over steps 1–8. Kendall tau-b and decision regret are averaged over the 36 anchors. Regret is actual `J` of the predicted-best direction minus actual `J` of the best direction in that same-amplitude set. These are descriptive repeated-anchor statistics, not independent-task estimates. [Full P0 summary](./evidence/20261025-cell-field-v4/p0-summary.json.gz), [compact tables](./evidence/20261025-cell-field-v4/p0-compact.json).

| Predictor | Absolute pooled loss RMSE | Mean same-amplitude J tau-b | Mean decision regret |
|---|---:|---:|---:|
| loss2 | 3.84330e-4 | 0.630556 | 6.52934e-6 |
| q4 | 7.48059e-4 | 0.484259 | 1.06447e-5 |
| history4 | 2.99434e-4 | 0.588426 | 1.06809e-5 |
| structured4 | 3.14990e-4 | 0.538889 | 1.12249e-5 |
| full | 1.74210e-5 | 0.993519 | 3.15107e-8 |

Structured4 improves pooled loss RMSE relative to loss2 but has worse same-amplitude ranking and regret. Q4 is worse on both loss RMSE and ranking. More coordinates or optimizer-aware coordinates do not alone establish reachable closure or a better decision rule.

| Amplitude | Full RMSE | Loss2 RMSE | Q4 RMSE | History4 RMSE | Structured4 RMSE |
|---|---:|---:|---:|---:|---:|
| 0.125 | 2.72377e-7 | 4.80107e-5 | 9.34869e-5 | 3.73795e-5 | 3.93257e-5 |
| 0.5 | 4.35750e-6 | 1.92072e-4 | 3.73967e-4 | 1.49565e-4 | 1.57348e-4 |
| 1.0 | 1.74210e-5 | 3.84330e-4 | 7.48059e-4 | 2.99434e-4 | 3.14990e-4 |

Full error grows approximately with squared amplitude over this range, while reduced-model error grows approximately linearly. This is a descriptive local scaling observation. Full error includes numerical derivative error and nonlinear remainder; this experiment does not isolate them or prove an asymptotic theorem for other checkpoints or architectures.

## 4. Objective pricing and compute are separate from prediction accuracy

The common `direct_soft` score is `0.03 * sum(w_k * delta_current_loss_k) + 0.5 * sum(w_k * positive_old_excess_k^2) + 0.5*h*0.1*||u||^2`, with stage weights `h=0.02` and terminal weight 1. Old excess is relative to the original warmup old-probe NLL. The final term is a parameter-coordinate intervention penalty; it is not elapsed time, FLOPs, or energy.

Zero is the actual minimum-J action in **36/36 fixed libraries**. Every one of the **1,728 nonzero actions** has worse J than zero. Nevertheless, **288/576 actions at each amplitude improve the direct current-risk term**. The compact decomposition preserves the separate risk, forgetting, and effort components. [Direction/amplitude decomposition](./evidence/20261025-cell-field-v4/p0-compact.json).

| Amplitude | Physical impulse norm | Charged action penalty | Range of actual J minus zero J |
|---|---:|---:|---:|
| 0.125 | 0.0025 | 1.56250e-5 | 1.00692e-5 to 2.11939e-5 |
| 0.5 | 0.0100 | 2.50000e-4 | 2.27854e-4 to 2.72355e-4 |
| 1.0 | 0.0200 | 1.00000e-3 | 9.55914e-4 to 1.04492e-3 |

This explains why high whole-pool J ranking can be dominated by amplitude/effort ordering. Same-amplitude ranking holds the intervention penalty fixed and tests directional discrimination. Zero's superiority is confined to the registered finite library; it does not prove that zero minimizes the continuous action problem. The MPC solver can choose smaller interventions.

The results support keeping three questions separate: whether a critic predicts a fixed action, whether the development objective prices that action usefully, and whether executing the resulting policy improves held-out performance at an acceptable compute cost. A more accurate full critic cannot by itself repair objective misalignment with future-task NLL.

## 5. P1: sealed causal policies and the predeclared scientific gate

All seven policies perform eight actual Adam updates from the same warmup. Every nonzero policy replans from its complete current state before each update and executes only the first planned action. Myopic uses a genuine H1 reference and constructs only Full; each H8 policy constructs only its own selected predictor. This avoids charging unused structured derivatives to other policies. The action box is common across policies. The candidate was fixed as **structured4_h8**; no final-label-based policy selection occurs.

The primary family has 12 contrasts: for each of four task/head combinations, candidate future NLL versus myopic, candidate future NLL versus loss2, and candidate old-test NLL versus its warmup. Differences are candidate minus comparator. The three fitted seed differences are averaged **per source example before resampling**. There are 10,000 class-stratified source-component bootstrap replicates, seed 20261025, with a one-sided `higher` percentile at `1-0.05/12 = 0.9958333333`.

Future improvement requires the upper bound to be **strictly below -0.001** against both baselines. Retention requires the upper bound to be **at most 0**. The Bonferroni allocation is explicit; percentile bootstrap coverage remains approximate and conditional on the selected sources and three fitted seeds. Actions, anchors, and fitted seeds do not multiply the number of independent source components. [Evaluator](./cell_field_evaluate_v4.py), [full evaluation](./evidence/20261025-cell-field-v4/evaluation.json).

Each CPU ratio is the sum of candidate CPU across the three paired seeds divided by the sum of myopic CPU, with an inclusive limit of 3.0. It is not the unweighted mean of three ratios and is not the parameter-action penalty.

| Task / head | Future vs myopic: mean, upper | Future vs loss2: mean, upper | Old vs warmup: mean, upper | Candidate / myopic CPU |
|---|---:|---:|---:|---:|
| UCI / linear | +0.000788, +0.001376 | +0.000523, +0.000968 | -0.046204, +0.036883 | 13.0651x |
| UCI / gated | +0.000463, +0.000898 | +0.000268, +0.000595 | -0.065998, +0.003728 | 12.7370x |
| 20NG / linear | +0.001505, +0.002179 | +0.001011, +0.001534 | -0.092472, -0.033504 | 11.1822x |
| 20NG / gated | +0.001270, +0.001848 | +0.000802, +0.001235 | -0.048415, +0.007046 | 12.5194x |

Only 20NG/linear retention passes. All eight future-improvement criteria fail; all four CPU criteria fail. Negative old-test mean differences describe improvement in the sampled mean. The three positive upper bounds mean that the strict non-inferiority claim is not established; they are not proof of observed average harm.

### All seven policies: descriptive future-test performance

Each entry is mean NLL / mean accuracy percent across the same three seeds. These additional policy comparisons do not select a replacement candidate or create new confirmatory claims. Every underlying current/future/old record and paired seed difference remains in the evaluation artifact.

| Policy | UCI / linear | UCI / gated | 20NG / linear | 20NG / gated |
|---|---:|---:|---:|---:|
| zero | 1.323873 / 34.821 | 1.342858 / 35.417 | 1.269089 / 46.094 | 1.306567 / 45.313 |
| myopic_full_h1 | 1.323232 / 34.524 | 1.342481 / 35.714 | 1.267104 / 46.094 | 1.304836 / 45.313 |
| loss2_h8 | 1.323497 / 34.524 | 1.342676 / 35.714 | 1.267598 / 46.094 | 1.305304 / 45.313 |
| q4_h8 | 1.324003 / 34.524 | 1.342458 / 35.714 | 1.267591 / 46.094 | 1.304505 / 45.313 |
| history4_h8 | 1.323961 / 34.524 | 1.342925 / 35.714 | 1.268523 / 46.094 | 1.306027 / 45.313 |
| structured4_h8 | 1.324020 / 34.524 | 1.342945 / 36.012 | 1.268609 / 46.094 | 1.306106 / 45.313 |
| full_h8 | 1.323597 / 35.119 | 1.342746 / 36.012 | 1.267557 / 46.094 | 1.305110 / 45.313 |

Full has the strongest fixed-action forecast, yet its H8 policy also has worse mean future NLL than myopic in all four groups. Small accuracy differences and ties are compatible with NLL differences because NLL measures the full probability assignment.

## 6. Retention pressure: binding, infeasibility, and transfer

For each warmup, an unforced current-task trajectory searches up to 256 steps for the first strictly positive old-probe excess. Prevention is at `max(0,tau-8)` and recovery at `tau`; the original warmup threshold is preserved. All 12 searches found crossings and produced all 24 checkpoints. At each checkpoint, zero plus five models by three budgets by two objectives gives 31 registered slots: **744 total**. No-pressure, infeasible, or unresolved cases would be retained rather than replaced with zero. [Pressure implementation](./cell_field_pressure_v4.py), [P0 pressure census](./evidence/20261025-cell-field-v4/p0-compact.json).

| Slot disposition | Count |
|---|---:|
| Executed | 551 |
| Tangent infeasible with box-separation witness; not executed | 174 |
| Numerically unresolved; not executed | 19 |
| Total registered | 744 |

All 24 zero branches violate the future **controller-probe** path constraint. The 167 executed matched hard/soft pairs all choose different actions. Actual hard feasibility holds in 18 pairs: six where soft also passes and 12 hard-only rescues. Those 12 rescues are concentrated in only **three distinct checkpoints**. The other 149 hard plans violate the actual nonlinear probe path. Hard tangent constraints therefore demonstrably bind, while tangent qualification is not a nonlinear retention certificate. The solver's declared feasibility tolerance is `1e-9`; it does not relax the scientific retention margin.

Held-out old-test paths were scored after the seal, against their own warmup old-test NLL. Among the same 167 hard/soft pairs, **79 both pass, 88 both fail, zero are hard-only rescues, and zero are soft-only rescues**. All 360 pair slots remain recorded, including 193 unavailable pairs. Across the 24 zero controls, independent old-test paths split 12 pass / 12 fail. The all-zero probe failure must not be presented as all-zero held-out failure. These path comparisons are descriptive mean-NLL outcomes, separate from P1's confidence-bound gate. [Independent retention paths](./evidence/20261025-cell-field-v4/pressure-retention.json), [complete paired census](./evidence/20261025-cell-field-v4/pressure-independent-pairs.json).

## 7. Replay, native governance, and qualification

The final [replay audit](./evidence/20261025-cell-field-v4/replay-audit.json) verifies 57 historical source files, 324 checkpoint bindings, and all 4,857 sealed files before and after replay. It reconstructs seeded warmups, replays every fixed branch (14,112 optimizer updates), and compares every saved state and both probe losses exactly. For all 12 structured4 policies it replays the prefix, independently restores the midpoint, recomputes the next plan, and replays the last four frozen actions. Midpoint maps/action maximum error is zero; terminal state digests and probabilities are exact. The sealed run is unchanged.

The auditor is post-execution verification tooling, not a changed analysis policy. Two rejected zero-fit attempts are preserved: a [CLI pin typo](./evidence/20261025-cell-field-v4/replay-audit-cli-pin-error.json) and a [protocol-copy schema assumption](./evidence/20261025-cell-field-v4/replay-audit-protocol-copy-error.json). The runner canonicalizes its protocol copy; its raw SHA256 is `89b7bed85d5e4b28220ff9aa3d3f46921d33c64dd255dba28dc99e489bb916fe`. The corrected auditor verifies the original pre-outcome file's fixed hash and exact semantic equality with the sealed copy. No executing source, candidate, numerical analysis rule, or state binding changed.

The additive native review API binds reviewer/policy, operation ID, report, admission/payload, predecessor head, and review validity; it checks strict task and inclusive retention/cost gates before entering owner publication. Its tests cover tampering, retry identity, withdrawal/frontier behavior, and unchanged owner state on rejection. Host-installed reviewer/policy, authenticated withdrawal feed, and trusted host time remain explicit trust assumptions. A signed statement commits evidence; it does not independently prove that the evidence is scientifically correct. [Native qualification](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/dot/cell-native-scientific-review-v4-20261025/qualification/scientific-candidate-review/README.md).

The actual driver loads the full 264-record census, 12 primary contrasts, four cost contrasts, and all 12 fitted candidate/predecessor states. It recomputes the declared aggregate gates and submits the real negative review with public ephemeral research keys. The native publication gate returned **`GateFailed(task)`** before entering owner publication; all **10 owner files** and the registry head remained unchanged. The signed review bytes/public key are retained. This validates rejection against real evidence; it does not install production trust. [Native rejection](./evidence/20261025-cell-field-v4/native-rejection.json), [gate input](./evidence/20261025-cell-field-v4/gate-input.json).

The actual parameter bundles are opaque float64 research artifacts containing all 12 heads and optimizer states. They are not native Q24 serving parameters and are not wired to a daemon selector. Positive native unit fixtures can create only Candidate artifacts; no actual trained candidate was published or activated. The negative-only real-report driver would still return MissingReview if all numeric gates unexpectedly passed.

Python qualification comprises **40 distinct tests**: dynamics 6, pressure 6, tradeoffs 3, data 4, evaluator 7, joint runner 3, summary 6, and replay 5. The native crate suite passed **102 tests, including 10 added gate tests**. One preexisting child-worker entry is ignored as a standalone test and is invoked by its passing parent crash/reopen matrix. These engineering tests do not convert the negative scientific result into a positive result. [Test counts and source hashes](./evidence/20261025-cell-field-v4/qualification.json).

## 8. Costs and practical limits

The actual head experiment consumed **618.6117 CPU seconds / 618.7164 wall seconds**, excluding encoder extraction. The two task feature-extraction runs together consumed **142.7196 CPU seconds / 39.7442 wall seconds** across 54 encoder forward calls; model loading is separately recorded in each feature report. Dense reference preparation, selected-model derivatives, solver, and actual advance are included in policy CPU ratios. Encoder and warmup costs are separately recorded; projection and serialization remain in overall runner overhead rather than being attributed to individual policies. Preparation totals already include the reference, so adding both would double-count. [Run manifest](./evidence/20261025-cell-field-v4/run-manifest.json.gz), [UCI features](./evidence/20261025-cell-field-v4/features/uci-report.json), [20NG features](./evidence/20261025-cell-field-v4/features/newsgroups-report.json).

Recorded runtime: Python 3.12.14, NumPy 2.3.5, SciPy 1.17.0, Linux x86_64. Encoder packages: Torch 2.10.0+cpu, Transformers 4.57.3, tokenizers 0.22.2, safetensors 0.6.2. Head work uses `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1`; encoder extraction sets four Torch threads. Timings are measurements of this implementation on this host, not universal complexity bounds.

There are **two task families, not 12 independent tasks**. Heads, seeds, anchors, actions, and pressure slots share source data. The heads are tiny, full-batch training is deterministic, and the horizon is eight steps. The study does not test encoder adaptation, transformer optimizer-state compression, stochastic minibatch diffusion, long-running memory, biological neurons, unlearning, or end-to-end agent behavior. Dense full-state construction remains a deployment limitation for every compressed predictor.

## 9. Comments on Parameter Field Theory and Hepta

The relevant paper snapshot is [R45 at f8df0a6075f58f3ab9431a889b773cdf8d6e771d](https://github.com/TrillionniumFoundation/ICLR-2027/tree/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45). Its useful contribution here is a precise separation between a retained field, its reachable dynamical closure, information restriction, actuation restriction, coefficient error, and nonlinear remainder. A field is not sufficient merely because it has an interpretable name or a small dimension.

V4 supplies a direct Hepta test of that separation. All five predictors share the same physical action space, so the fixed-action comparison does not confound observation compression with actuator restriction. The full theta/m/v tangent captures optimizer memory much better locally; the tested four-dimensional constructions do not close the dynamics sufficiently to preserve its action ranking. This supports optimizer-state-aware analysis while leaving the search for a useful small field open.

The results also show why forecast fidelity, objective choice, generalization, retention, cost, and authority need distinct evidence. Full's local predictive success does not establish that H8 planning improves future NLL. A hard probe constraint does not establish held-out retention. Exact replay does not establish either scientific benefit or publication authority. The paper's restricted exact-cache results likewise cannot be extended to arbitrary trainable backbones; Hepta's feature reuse here is exact because its encoder is frozen.

The warranted next research step is a newly frozen, source-independent experiment targeting a specific failure: a cheaper causal observer with measured construction cost; an objective calibrated to declared task/retention utility; or robust nonlinear retention control with fresh independent evaluation. The present final labels must not be reused to tune and then reconfirm the candidate. Native admission should continue to require host-installed scientific review and explicit serving compatibility.

## 10. Reproduction and evidence map

Use an authorized research checkout, an authorized native-branch checkout, and fresh output directories. The source-acquisition helper is post-run reproducibility tooling: it verifies exact historical source bytes, including source-only V1 reconstruction, without parsing historical prediction/score/label payloads. [Acquisition receipt](./evidence/20261025-cell-field-v4/acquisition.json). A fresh execution records its own source closure; it does not replace the original run's seal.

```bash
# Start at the research repository root; set the separate native checkout path.
V4_REPO="$PWD"
V4_NATIVE=/absolute/path/to/native-checkout
V4_WORK=/tmp/hepta-cell-field-v4-reproduction
python3.12 -m venv "$V4_WORK/venv"
V4_PY="$V4_WORK/venv/bin/python"
"$V4_PY" -m pip install numpy==2.3.5 scipy==1.17.0 transformers==4.57.3 tokenizers==0.22.2 safetensors==0.6.2
"$V4_PY" -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.10.0+cpu
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
cd "$V4_REPO/qa/stem-bakeoff"
V4_PROTOCOL="$PWD/cell_field_joint_protocol_v4.json"
V4_PIN=30880ddaae978f622cf6a99cf3888771daa954777e6f9ce2a75c25f01f166280
"$V4_PY" cell_field_acquire_v4.py --output "$V4_WORK/inputs" --verify-v1-reconstruction
"$V4_PY" cell_field_data_v4.py --uci-archive "$V4_WORK/inputs/uci-news.zip" --newsgroups-archive "$V4_WORK/inputs/20news-bydate.tar.gz" --prior-directory "$V4_WORK/inputs" --protocol "$V4_PROTOCOL" --output "$V4_WORK/data"
"$V4_PY" cell_field_snapshot_v4.py --snapshot "$V4_WORK/snapshot"
for v4_task in uci newsgroups
do
  "$V4_PY" cell_field_features.py --data "$V4_WORK/data/$v4_task" --snapshot "$V4_WORK/snapshot" --protocol "$V4_PROTOCOL" --output "$V4_WORK/features/$v4_task"
done
"$V4_PY" cell_field_joint_run_v4.py --data "$V4_WORK/data" --features "$V4_WORK/features" --protocol "$V4_PROTOCOL" --output "$V4_WORK/run"
"$V4_PY" cell_field_summary_v4.py --root "$V4_WORK/run" --protocol "$V4_PROTOCOL" --output "$V4_WORK/p0-summary.json"
"$V4_PY" cell_field_compact_v4.py --summary "$V4_WORK/p0-summary.json" --output "$V4_WORK/p0-compact.json" --full-gzip "$V4_WORK/p0-summary.json.gz"
"$V4_PY" cell_field_score_v4.py --run "$V4_WORK/run" --data "$V4_WORK/data" --protocol "$V4_PROTOCOL" --output "$V4_WORK/evaluation"
"$V4_PY" cell_field_replay_v4.py --run-directory "$V4_WORK/run" --protocol-path "$V4_PROTOCOL" --expected-protocol-sha256 "$V4_PIN" --output "$V4_WORK/replay-audit.json"
"$V4_PY" cell_field_native_bundle_v4.py --run "$V4_WORK/run" --protocol "$V4_PROTOCOL" --report "$V4_WORK/evaluation/evaluation.json" --output "$V4_WORK/bundle"
cargo +1.95.0 run --locked --manifest-path "$V4_NATIVE/qualification/scientific-candidate-review/actual-review-driver/Cargo.toml" -- "$V4_PROTOCOL" "$V4_WORK/evaluation/evaluation.json" "$V4_WORK/bundle/gate-input.json" "$V4_WORK/bundle/predecessor-parameters.json" "$V4_WORK/bundle/candidate-parameters.json" "$V4_WORK/native-rejection"
```

The pinned top-level Python package versions above describe the recorded runtime; transitive package resolution and another host's floating-point/timing behavior are not claimed to be a fully locked environment. Archive/model hash checks reject changed downloads. The actual native driver verifies the fixed scientific definitions and cannot promote a replacement policy.

| Evidence group | Persisted files |
|---|---|
| Acquisition and cohorts | [acquisition](./evidence/20261025-cell-field-v4/acquisition.json), [data manifest](./evidence/20261025-cell-field-v4/data-manifest.json), [source audit](./evidence/20261025-cell-field-v4/source-audit.json), [dataset definitions](./evidence/20261025-cell-field-v4/source-datasets.json) |
| Role and source receipts | [UCI](./evidence/20261025-cell-field-v4/data/uci-receipt.json), [20NG](./evidence/20261025-cell-field-v4/data/newsgroups-receipt.json) |
| Frozen feature extraction | [UCI](./evidence/20261025-cell-field-v4/features/uci-report.json), [20NG](./evidence/20261025-cell-field-v4/features/newsgroups-report.json) |
| Execution identity | [canonical protocol copy](./evidence/20261025-cell-field-v4/canonical-run-protocol.json), [executed source](./evidence/20261025-cell-field-v4/executed-source.json), [run manifest](./evidence/20261025-cell-field-v4/run-manifest.json.gz), [pre-evaluation seal](./evidence/20261025-cell-field-v4/pre-evaluation-seal.json) |
| P0 prediction/objective/pressure results | [full summary](./evidence/20261025-cell-field-v4/p0-summary.json.gz), [compact indexed tables](./evidence/20261025-cell-field-v4/p0-compact.json) |
| Label access and science | [label access](./evidence/20261025-cell-field-v4/label-access.json), [evaluation](./evidence/20261025-cell-field-v4/evaluation.json), [independent retention](./evidence/20261025-cell-field-v4/pressure-retention.json), [scientific review](./evidence/20261025-cell-field-v4/scientific-review.json) |
| Independent pressure pairing | [all 360 pair slots](./evidence/20261025-cell-field-v4/pressure-independent-pairs.json) |
| Replay and rejected audit attempts | [final audit](./evidence/20261025-cell-field-v4/replay-audit.json), [CLI pin error](./evidence/20261025-cell-field-v4/replay-audit-cli-pin-error.json), [protocol-copy error](./evidence/20261025-cell-field-v4/replay-audit-protocol-copy-error.json) |
| Native real-report rejection | [gate input](./evidence/20261025-cell-field-v4/gate-input.json), [candidate states](./evidence/20261025-cell-field-v4/candidate-parameters.json), [predecessor states](./evidence/20261025-cell-field-v4/predecessor-parameters.json), [native receipt](./evidence/20261025-cell-field-v4/native-rejection.json) |
| Qualification and archive inventory | [qualification](./evidence/20261025-cell-field-v4/qualification.json), [evidence index](./evidence/20261025-cell-field-v4/evidence-index.json), [complete-archive receipt](./evidence/20261025-cell-field-v4/complete-archive.json) |

These 29 evidence files retain negative/unavailable outcomes as recorded. Compact and full P0 summaries are linked by hashes. The full original run, raw NPZ/checkpoints, separate held-out labels, and subsequent evaluation/audit evidence are retained in `cell-field-v4-complete-evidence.tar.gz`: 86,587,644 bytes, SHA256 `a0a7f56aaabd2f9db778933fcc26bc8e4828f2d11a7e8a78f1776ef081cee275`. The archive is supplied separately to the user; the repository contains its receipt and compact review evidence. Encoder weights, original text corpora, and repository code copies are excluded from that archive and are obtained by the reproduction procedure.
