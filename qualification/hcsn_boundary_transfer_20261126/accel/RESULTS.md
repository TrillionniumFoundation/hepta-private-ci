# Accelerator, frozen semantic hybrid and conditional readout results

All RTX rows below were produced on one NVIDIA GeForce RTX 4060 with real PyTorch CUDA forwards, backward or analytic solves and reopened state dictionaries. The physical body is the repository SmallHCSN with its QVI, six price bins, eight neurons, three stages and precision-mixed population dynamics. The centered arm changes only the outgoing boundary message for the subsequent step using the nominal stationary boundary. Source timing advances in six 0.48-second increments. In this independently frozen comparison, new inputs arrive every tick and slow controls update on the original model schedule. The separately studied cue accumulator uses a different intervention. Two-candidate retrieval scores each candidate independently with the same parameters and charges equivalent observations. The three seeds use the same held-out historical actors. Percentages averaged over seeds do not create more independent actors.

## Fresh fits on actor-disjoint RAVDESS

Training had 80 queries on 10 actors, development 32 on 4, retention 32 on 4 and final test 48 on 6. Each row below compares three independently trained heads, 24 AdamW updates each; 330 parameters for HCSN, 474 for GRU and 698 for causal attention. The held-out actor sets were previously used in repository research. All 12 checkpoint hashes were sealed before final evaluation within each campaign. The table reports arithmetic means. Fit and evaluation are separate cold processes including interpreter launch, model and data loading, final CUDA synchronization, and disk-operation overhead in each phase. Prior visual-cache production and model pretraining are unmeasured historical costs.

|Input evidence | Network | Test | Retention | Test Brier | Cold fit s | Cold eval s | Utility gate |
|---|---|---:|---:|---:|---:|---:|---:|
| Frozen acoustic/visual distance | Fixed comparator | 66.67% | 75.00% | — | — | — | — |
| Same | HCSN centered | 66.67% | 82.29% | 0.22943 | 13.625 | 4.241 | 0/3 |
| Same | HCSN raw | 66.67% | 82.29% | 0.22945 | 13.310 | 4.214 | 0/3 |
| Same | GRU | 76.39% | 92.71% | 0.17096 | 5.167 | 3.302 | 3/3 |
| Same | Causal attention | 72.92% | 91.67% | 0.17335 | 5.386 | 3.465 | 3/3 |
| Frozen Wav2Vec2 + visual distance | Fixed comparator | 83.33% | 78.13% | — | — | — | — |
| Same | HCSN centered | 85.42% | 84.38% | 0.17997 | 13.504 | 4.597 | 0/3 |
| Same | HCSN raw | 85.42% | 84.38% | 0.17997 | 14.088 | 4.428 | 0/3 |
| Same | GRU | 97.92% | 98.96% | 0.03115 | 5.411 | 3.534 | 3/3 |
| Same | Causal attention | 100.00% | 100.00% | 0.00587 | 5.504 | 3.718 | 3/3 |

The gate required at least one additional correct development example versus the shared starting point, held-out accuracy at least 62.5%, strict test improvement and retention at least baseline. The frozen semantic HCSNs gained one test query and two retention queries versus their fixed comparator for each seed. None gained a development query. The controls beat HCSN in accuracy and time under this budget. This experiment establishes no HCSN speed win over an equally accurate sequence model and sets no convergence limit for longer runs. No energy, event sparsity or end-to-end foundation-model training was measured.

The semantic cache used the frozen 94,395,552-parameter CTC encoder at Hugging Face revision 22aad52d435eb6dbaf354bdad9b0da84ce7d6156, each of 192 original hash-checked MP4s and six individually truncated prefixes per recording. Acoustic distances are computed from nonblank CTC posterior histograms, and combined with the original frozen visual motion distances with train-only scaling. GPU model loading, source validation and decoding took 21.481 s, the 1,152 prefix inferences 4.457 s, and full preparation 26.160 s. These shared costs can be charged once to a cohort or to each individual arm when starting from the same raw speech. Original visual-cache computation and the foundation encoder's pretraining remain outside both scopes. The original CTC checkpoint omits a training-only SpecAugment parameter. The evaluation frontend expressly disabled augmentation and required zero missing/mismatched inference weights before running.

## Comparable closed-form and iterative gradient updates to the same frozen head

The two final output rows of the trained centered HCSN can encode a signed margin update. With frozen features, train-only column scaling, label residual y and ridge parameter 0.5, minimize the quadratic loss ||Xw-y||²/(2n) + 0.5||w||²/2. The direct fit solves the positive-definite normal equations in float64. The iterative arm minimizes the same objective by PyTorch autograd with strong-Wolfe L-BFGS. An opposite signed projection updates the two output rows, followed by recomputation of every physical prediction from the sealed network. Each solver starts from the identical parent and data for each of the three seeds; parent fitting used BP. All six edit hashes were sealed before final testing and retention. The largest absolute directly reconstructed margin minus network margin was 0.00000539; the largest direct versus iterative Brier difference by split and seed was below 0.00000007. Eight gradient closures ran in each iterative fit. These tests use repeatedly observed actors and provide conditional evidence about this particular fixed representation.

| Per-seed average wall scope | Direct s | L-BFGS s | L-BFGS/direct |
|---|---:|---:|---:|
| CUDA-synchronized solver/optimizer construction and solve | 0.0356 | 1.3212 | 37.10× |
| Complete cold edit fit | 4.568 | 6.268 | 1.372× |
| Fresh cold parent + edit evaluation | 4.696 | 4.536 | 0.966× |
| Cold edit fit plus cold evaluation | 9.264 | 10.804 | 1.166× |
| Shared speech preparation + cold parent training + cold edit fit + cold final evaluation | 48.928 | 50.468 | 1.031× |

Both solvers reached 42/48 held-out correct (87.50%) versus 41/48 for the frozen parent, and 31/32 retention correct (96.875%) versus 27/32 for the parent. Direct and L-BFGS made identical class predictions on all 80 test/retention queries for each seed. Against the parent, the test gain was one changed query on one actor with no new error, and the four retention gains came from four actors with no new error. Both satisfied the additional improvement condition in all three matched pairs. Actual savings in the largest measured scope were 1.54 seconds, equivalent to a 3.05% reduction. This result establishes a same-quality direct update to one convex readout under this protocol. It leaves encoder pretraining, end-to-end model learning, energy, fresh actor generalization, and whole-network editing speed outside the tested scope. Strong-Wolfe L-BFGS is one iterative comparator. Solver construction and first CUDA calls are charged to it, and brief GPU measurements on a shared machine can vary. These ratios are observations rather than hardware-independent algorithmic constants.

## Reproduction and verification

Use the original qualification source at Git commit c4ae70d44613434aaf165529a6076fa3400ca431 and RAVDESS paired source cache in 419cc6fba3ce7f1cdde6b96bbf92bc3e324c0560 under qualification/hcsn_qvi_retrieval/evidence/inputs.zip. benchmark.py checks the four original cache digests. semantic_frontend.py checks each original MP4, CTC weight/config and cache, then generates the hash-bound semantic entrypoint. For the semantic campaign, place public originals from RAVDESS (doi:10.5281/zenodo.1188976; CC BY-NC-SA 4.0) in media-cache under the input cache beside the original four receipt files. Use the pinned model.safetensors and config.json and the exact weights in frontend_receipt.json. All run directories must be fresh.

```bash
export PYTHONPATH=/path/to/hepta-private-ci
python benchmark.py run --data /work/original --out /work/run
python semantic_frontend.py --original /work/original --model /work/pinned-ctc --base-code benchmark.py --output /work/neural
python /work/neural/semantic_executor.py run --data /work/neural --out /work/neural_run
python readout_cost.py run --data /work/neural --parents /work/neural_run --out /work/quadratic
python summarize.py lowlevel_results.json /tmp/lowlevel_summary.json
python summarize.py semantic_results.json /tmp/semantic_summary.json
python verify_readout.py
```

lowlevel_results.json and semantic_results.json contain all 48 fit/eval rows, every final forecast, actor group and label. readout_results.json includes all 12 additional fits/evaluations. verify_readout.py checked all 30 state dictionaries against both the archived stage seal and the recorded fit identity. Independently recomputed prediction metrics differ from their original GPU reductions by at most 7.1e−8. The archive stores candidate state dictionaries and three stage seals, without recordings or pretrained foundation weights.

## Independent T4 request

Six configured Colab/Kaggle slots were inspected. Two slots at each provider were ready, and one slot at each provider was reserved. One private Colab T4 plan requested one centered HCSN and one causal attention arm at four updates, seed 193. The archive t4_payload.zip contains the exact frozen submission, t4_submitted.py (152,598 bytes, SHA-256 5311806b8fdd145b6987bab0495b70f7e234e7daf11abfba6583443977afcf2c). Extracting that member reproduces the submitted bytes. Its assignment POST timed out, then a later read-only observation temporarily recovered the same T4 allocation under the original key. The allocator confirmed one runtime attempt. Binding the original fixed runtime returned FIXED_RUNTIME_NOT_FOUND. Subsequent inspection retained RECONCILIATION_REQUIRED with the original bind outcome unknown, no scientific run in the ledger, and no T4 metrics. The campaign used one provider identity and requested one allocation. cloud_status.json identifies the original request, phases and final collection result. All numeric network results in this report are RTX 4060 observations.
