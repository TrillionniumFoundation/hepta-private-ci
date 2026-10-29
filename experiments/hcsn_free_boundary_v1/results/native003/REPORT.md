# Native003: trained stopping heads on a fixed HCSN backbone

## Finding

The extension successfully trains a price-conditioned stopping head and sends its continuous score through the original native owner. Actual native STOP ends the model loop, so later prefixes are not computed. This establishes an executable, trainable controller on this frozen backbone. It does **not** establish an advantage over a strong ordinary controller or an advantage of the HCSN neuron architecture.

The registered comparison initially gives the value-feature head a macro read utility of **0.127708**, compared with **0.076563** for the matched 33-parameter MLP. The selected MLP, however, stops after the first prefix at every price. A separately labelled, posthoc adversarial audit selects ordinary fixed prefixes from the saved validation traces and obtains **0.173333**, exceeding the value head by **0.045625**. The value head wins none of that audit's 36 complete CPU-cost scenarios. Both results remain preserved; the latter limits how the former can be interpreted.

Primary machine-readable evidence is [SUMMARY.json](SUMMARY.json), [COST_SCENARIOS.json](COST_SCENARIOS.json), and the [read-only receipt audit](REVIEW.json). The separate [adversarial report](../native003_adversarial001/REPORT.md) describes its selection, actual additional computation, reuse, costs, and posthoc status.

## Scope fixed before fresh inference

This is one conditional MNIST stopping-head pilot: one previously trained `free_dual` backbone, one head initialization seed, two learning rates, and 128 updates for each learning-rate candidate. It is not a new backbone training comparison, a multimodal model result, a Transformer/SNN comparison, or a population-level significance result.

The fixed backbone is `study001/runs/mnist/free_dual/9101`, width 32, depth 1, selected learning rate 0.003 and update 134. Its checkpoint SHA-256 is `069ecacf9fa21cb8e4360893a2d6aa68621a1860d4baa6b9ae1c7343df289cfd`. The original complete training process consumed 46.474767 CPU seconds; that prior cost is charged in deployment scenarios and is separate from newly executed native003 work.

[NATIVE003_PROTOCOL.json](../../NATIVE003_PROTOCOL.json) was frozen before training or fresh inference. Its SHA-256 is `4c7fdccfe1d4adee9628de10e71741368e8ecdd1b2e6524084c8799aec7d0560`. [FREEZE.json](FREEZE.json), identity `6185052d4a27088e9c4cc76db297cb5aca7322628d705938b9d4e0ca7bc5e79a`, locks 54 source, protocol, data, and backbone artifacts. The original main study's 38-file freeze remains unchanged. The receipt audit rechecked all these hashes after both native003 and the posthoc audit.

Training uses prefix traces from the first 256 original training episodes. Learning-rate/checkpoint selection uses the first 128 original validation episodes. The new test cohort contains the next 128 MNIST source images after the original frozen 512 test episodes: the deterministic test-generation slice `[512:640]`, data seed 912201. All 128 are unique and have zero source-image or episode-ID intersection with the old train, validation, and test cohorts. The generator exactly reproduced the old 512 test arrays and metadata before taking the new slice. It copied the original train-fitted transformation and fitted no new statistics. These generation checks do not perform model inference.

Fresh data SHA-256 is `9964a9db1915fea08873f4f56f25f43cf0c37155af78502766eb4ff502f0148f`; its [manifest](../../data/native003/fresh_mnist.json) records the source hashes, reproduction, transformations, and disjointness checks. The complete generation subprocess consumed 0.614690 CPU seconds. The three price scenarios reuse the same 128 images, so they are **128 episode units**, not 384 independent observations.

## Heads, objective, and selection

All head families receive these six causal, current-prefix observations:

1. `tanh(mean(J))`, the model's stationary regenerative threshold-policy envelope;
2. `tanh(mean(margin))`;
3. risk `1 - max(softmax(logits))`;
4. mean first-passage event probability;
5. elapsed observation time divided by 32;
6. public per-read price.

Labels and future-prefix outcomes are excluded from the head inputs. Offline prefix correctness is used only as a training reward or validation metric. Feature normalization is fitted to the training traces and public price grid. The receipt audit independently reproduced the means and standard deviations from the saved TRAIN traces, and checked correctness against saved predictions and labels. Full offline prefix generation is charged to training and selection; it is not presented as inference compute saved by stopping.

| Family | Formula or structure | Trainable parameters |
|---|---|---:|
| `value_maxout` | `max_j softplus(a_j) * softplus(W_j z + b_j) + b_out`, four branches | 33 |
| `ordinary_mlp` | Linear 6→4, tanh, Linear 4→1 | 33 |
| `risk_threshold` | Risk minus a learned sigmoid threshold conditioned on public price | 2 |

The first family is a **positive scaled softplus max-pool head**. The historical identifier `value_maxout` is retained in artifacts; it is not a literal maximum of affine functions and is not a task-optimal boundary derived from the scalar regenerative oracle. Its branch scales affect the soft policy, but do not expand its hard stopping boundary class in the usual negative-output-bias regime. Matching parameter counts does not make the function classes or CPU costs equal.

The differentiable objective is the expected value of `correct_at_stop - price * observed_prefix_count` under first-stop survival probabilities. A sigmoid of negative score with fixed temperature 0.1 gives each nonterminal stop probability; final-prefix stop probability is forced to one. Read counts start at one. No additional controller tuning occurs on fresh data.

Every family uses seed 440031, the same minibatch stream, batch size 64, Adam, learning rates 0.003 and 0.01, and 128 updates per candidate. Checkpoints at updates 32, 64, and 128 are evaluated using the hard Q24 stopping rule on validation only. Selection maximizes mean validation utility across the three prices, with ties resolved by earlier update and then lower learning rate. All candidate outcomes remain in `head_search/`. [TRAINING_LOCK.json](TRAINING_LOCK.json) pins selected numeric checkpoint files before fresh inference.

| Family | Selected LR | Selected update | Validation macro utility | Complete measured two-LR family search CPU |
|---|---:|---:|---:|---:|
| Value head | 0.01 | 128 | 0.137500 | 1.150757 s |
| Ordinary MLP | 0.01 | 32 | 0.084375 | 0.482087 s |
| Risk threshold | 0.01 | 128 | 0.069961 | 0.328976 s |

All 33 parameters in each matched family received a nonzero gradient at least once across its selected learning-rate candidate's full 128-update run. The audit records actual selected-checkpoint parameter changes separately. The selected value candidate's branch winner counts are `[17649, 2002, 4240, 685]`. The full-run gradient coverage is not a claim that all those updates occurred before the MLP's selected update 32.

## Registered fresh-cohort outcomes

Read utility is `correct - price * reads`; CPU is charged separately below. All entries use 128 fresh episodes. Fixed references execute their own actual `model.step` calls to their stated prefix; they are not assigned costs from precomputed test traces.

| Policy | Accuracy at 0.005 / 0.02 / 0.05 | Mean reads at 0.005 / 0.02 / 0.05 | Utility at 0.005 | Utility at 0.02 | Utility at 0.05 |
|---|---|---|---:|---:|---:|
| Value head | 54.6875% / 27.3438% / 10.1563% | 32 / 16.4375 / 1 | 0.386875 | −0.055313 | 0.051563 |
| Ordinary MLP | 10.1563% / 10.1563% / 10.1563% | 1 / 1 / 1 | 0.096563 | 0.081563 | 0.051563 |
| Risk threshold | 9.3750% / 9.3750% / 9.3750% | 1.882813 / 1.546875 / 1.078125 | 0.084336 | 0.062813 | 0.039844 |
| Read all | 54.6875% at each price | 32 at each price | 0.386875 | −0.093125 | −1.053125 |
| Fixed 8 | 5.4688% at each price | 8 at each price | 0.014688 | −0.105313 | −0.345313 |
| Fixed 16 | 14.8438% at each price | 16 at each price | 0.068438 | −0.171563 | −0.651563 |
| Fixed 24 | 30.4688% at each price | 24 at each price | 0.184688 | −0.175313 | −0.895313 |

At price 0.005 the value head never issues native STOP and reaches the finite horizon. Its predictions equal read-all predictions and it adds control overhead. At price 0.02 it stops 66 of 128 episodes, reducing reads to 16.4375 on average, but its negative read utility is below the MLP's immediate-stop utility. At price 0.05 it stops every episode after one observation. This is a price-sensitive tradeoff, not a uniformly favorable accuracy/cost improvement.

### Stronger ordinary check, explicitly posthoc

After the registered outcomes were known, an adversarial baseline family was requested: choose a fixed prefix separately for each public price using only the saved original validation traces. Candidate prefixes are `{1, 8, 16, 24, 32}`, with earliest-prefix tie breaking. The selected schedule is 32 at 0.005, then 1 at 0.02 and 0.05. Its choice and code were locked before the new fixed-1 computation. This is not a preregistered new confirmation on an unseen cohort, because the baseline family itself was proposed after the primary fresh outcomes.

| Price | VAL-selected ordinary prefix | Ordinary utility | Value-head utility | Value minus ordinary |
|---|---:|---:|---:|---:|
| 0.005 | 32 | 0.386875 | 0.386875 | 0 |
| 0.02 | 1 | 0.081563 | −0.055313 | −0.136875 |
| 0.05 | 1 | 0.051563 | 0.051563 | 0 |
| Equal-price macro | — | **0.173333** | **0.127708** | **−0.045625** |

The additional audit actually ran one prefix on each fresh image, with 128 real model calls. It transparently reuses the previously executed read-all reference at the low price and reuses the newly measured fixed-1 execution across the two higher prices. It does not copy MLP outputs in place of that new computation. All 128 new predictions agree with the old MLP's first-prefix predictions at every price. Full detail is retained in [the separate report](../native003_adversarial001/REPORT.md).

## Native actions, guards, and causal execution

The Python head computes a continuous score. The native profile consumes positive and negative coordinates of its bounded score using the original width-5, top-k-1 (20%) transport. Positive Q24 score selects KEEP, zero or negative score selects STOP, and the repair branch remains disabled by its fixed score. The original adapter, native executable, authority, and guards are unchanged. This is Python model/head inference connected to the real native owner; it is not a native implementation of the Torch head or a production deployment.

Across the complete native003 run and recovery probes, the audit counted 1,155 native episode records, 1,157 native child processes, 7,324 actual neural steps and owner ticks, 7,328 kernel calls, and 7,326 NDU calls. All child processes exited zero. All 964 recorded native errors are deliberate post-STOP rejection probes, each leaving the durable frontier unchanged. No unexpected native errors, float/Q24 action disagreements, or zero-score rounding ties occurred. The fixed references independently executed 30,720 model steps across 1,536 reference episodes.

Existing paired receipts give a direct price intervention check without new inference. For all 128 images, the first five nonprice features, first-prefix prediction, native profile, and native initial checkpoint are identical at prices 0.005 and 0.05. Changing only the public price changes actual native KEEP to STOP in all 128 pairs and total model calls from 32 to 1. For the first episode the learned score changes from 0.439181 to −0.406644. This proves the trained score controls real execution. It does not prove that every latent feature contributes independently or that this controller is better than an ordinary price rule. The earlier `native001` four-channel intervention fixture remains a separate engineering result.

The executable SHA-256 is `1dc702aea6a448ad84407aeb71dc8f23066205fab79fe7c6859fc02c55e6f7a5`, source base commit `5898cd8b0f724c3152b6cc52856721f72e5e08be`, wrapper commit `7bec42aa4f79432f4a724d5295c67f9d69ee5a8d`, and native source manifest digest `6addea031fa9ba2ca403137d8d10da6088c255474c681b106d9a2706c645dd09`. Authority remains `DENY_ALL`; the local research permits grant no production authority or external effects.

## Recovery and complete CPU accounting

At price 0.005, the value and risk heads each exercise one checkpoint/restart after a KEEP. Numeric recurrent state is serialized, a new model/head object is loaded, and a new native child resumes in the **same Python interpreter**. Both match their uninterrupted trajectories, including native checkpoint and NDU digests. The MLP stops at prefix 1, so its requested recovery has `recovery_count=0`: it provides no exercised recovery proof. Separate process-recovery work elsewhere in the package must not be attributed to this run.

| Measured item | CPU seconds | Accounting scope |
|---|---:|---|
| Complete head training worker | 4.752781 | Python/Torch import, trace generation, all three families/two LRs, validation, checkpoint/report I/O |
| Complete evaluation worker | 148.798548 | Python/Torch import, actual model/head/reference execution, native descendants, recovery and report I/O |
| Native child subtotal | 10.318937 | Nested detail already included in evaluation worker; never added again |
| Fresh-data generation | 0.614690 | Complete generation child |
| Orchestrator self CPU | 0.116302 | Cumulative self CPU through accounting cutoff |
| **New native003 total** | **154.282321** | Training + evaluation + generation + orchestrator, no descendant double count |
| Prior backbone training | 46.474767 | Previously executed, separately amortized in deployment scenarios |
| Additional posthoc audit | 2.538695 | Separate new fixed-1 worker + parent; not folded into the registered total |

Complete training/evaluation wall times were 5.643066 and 196.817063 seconds respectively. Their whole-child peak RSS values were 278,952 and 246,368 KiB. Process peaks are not summed as if they were simultaneous memory allocations. No Joules were measured, and CPU seconds are not hardware-energy estimates. The final two orchestrator report writes occur after the stated self-CPU accounting cutoff.

The deployment scenarios use:

`utility = mean(correct - price * reads) - lambda_CPU * [measured inference CPU/episode + (backbone training + full family search + shared train/trace setup + shared deployment setup + recovery verification) / N]`.

`N` is 1,000, 10,000, or 100,000; `lambda_CPU` is 0, 0.0001, 0.001, or 0.01 utility units per CPU second. Fixed references omit head search, training-trace, and recovery charges they do not require. Shared deployment setup is charged once in each alternative policy deployment, not added across policy alternatives. Shared trace/training CPU is 2.790961 seconds; shared deployment setup is 2.656002 seconds. The complete prior backbone search is charged rather than only the selected checkpoint's final training segment.

Representative measured inference CPU per episode, including native children for native policies, is:

| Policy | Price 0.005 | Price 0.02 | Price 0.05 |
|---|---:|---:|---:|
| Value head | 0.161069 s | 0.091742 s | 0.013955 s |
| Ordinary MLP | 0.013654 s | 0.015881 s | 0.017027 s |
| Read all | 0.105187 s | 0.117030 s | 0.104049 s |
| Posthoc actual fixed 1 | — | 0.003191 s | 0.003191 s, explicitly reused |

These are measured CPU costs in this shared single-thread CPU environment, not isolated hardware throughput guarantees. The read-only review reaggregated all 252 registered CPU scenarios and all 36 posthoc scenarios. It found no arithmetic or descendant-counting discrepancy.

## Interpretation retained with the evidence

The runnable result is a trained, causal, price-conditioned bridge from continuous neural features to actual native owner actions with guarded stopping and limited recovery validation. The selected value head's apparent advantage over the collapsed MLP is insufficient evidence of controller superiority: a simple validation-selected ordinary schedule does better here. One initialization, a small fixed search, one backbone, and 128 deterministic MNIST images do not establish a broad result about value-head function classes or HCSN versus other backbones. The underlying model also remains the explicitly documented stationary-oracle/mean-state neural approximation, not an exact stochastic free-boundary simulator or the original financial debt/equity system.

The registered summary SHA-256 remains `d77d73c891b4a5d0ab1b35008bee61a3d919693dee360bbb0618068f56c918ed`. No registered source, checkpoint, test result, protocol, or prior native002 negative result was changed to accommodate the audit.
