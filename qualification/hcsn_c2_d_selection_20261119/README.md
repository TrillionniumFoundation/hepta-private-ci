# D-only 21-model selection and actual artifact ledger

## Outcome and limits

The original seven-family, three-seed selection rule now has a concrete immutable roster. All seven families choose the common learning rate **.003** using their arithmetic mean D macro-F1 over seeds 101, 211 and 307. The 21 selected runs satisfy the recorded minimum-30-epoch, memorization and delta-.002/patience-10 plateau rules. This statement concerns recorded training adequacy; it does not establish independent full training replay.

All 21 exact selected checkpoints and saved D-logit artifacts have now been read and hashed. Checkpoint configurations, saved strict-best epochs, data-manifest identities, finite model tensors and tensor shape/dtype/bytes were checked without constructing a model or performing inference. Saved D logits reproduce the recorded D macro-F1. D is the development set used for selection, so these values are not held-out confirmation evidence or a claim that HCSN outperforms the baselines.

The original controller `1a1c74f3308-be2a-75` remains **UNKNOWN**, independent original C2 full training replays remain **0 / 6**, and scientific admission remains **HOLD**. No E features, labels or payload were opened. No calibration, E inference or scoring ran, and this ledger grants no execution authority or automatic trigger. The completed partial continuation in parent Draft #6751 is retained; its lower-scoring .001 fit is not substituted for the .003 common-LR winner.

## Common learning-rate selection

The selector retains all 42 opportunities, both learning rates, all three seeds, complete-epoch observations and original failures. It selects the first strict maximum complete-epoch checkpoint per opportunity, then compares the three-seed means for .001 and .003. An exact mean tie chooses .001. Adequacy is checked after choosing the winner; an inadequate winner must remain blocked rather than being replaced by the runner-up. The controls exercise that case.

| Family | Mean D at .001 | Mean D at .003 | Selected common LR | Selected recorded adequacy |
|---|---:|---:|---:|---:|
| gru | 0.229468246704676 | 0.424974746924639 | .003 | 3 / 3 |
| cfc | 0.267439662940568 | 0.349025077188091 | .003 | 3 / 3 |
| snn_plif | 0.116338799095038 | 0.149978695218197 | .003 | 3 / 3 |
| event_time_lif | 0.162596494735825 | 0.313030520840694 | .003 | 3 / 3 |
| ssm_s4d | 0.324356768218035 | 0.366865610888871 | .003 | 3 / 3 |
| attention | 0.397746306328122 | 0.402616522448808 | .003 | 3 / 3 |
| hcsn | 0.354896608888473 | 0.376252694889131 | .003 | 3 / 3 |

The unselected .001 CfC and PLIF groups retain their original two-of-three and one-of-three adequate counts. The HCSN .001 seed 211 continuation now reaches the original plateau rule, but its family mean remains below .003. The original selection policy therefore yields the same .003 HCSN choice.

## Actual byte bindings

The three bounded native read-only inventories matched exactly **21 checkpoints** totaling **2,883,548 bytes** and **21 saved D-logit files** totaling **64,496,697 bytes**. The saved model tensors occupy **879,360 bytes** in aggregate; checkpoint file sizes also contain serialization, optimizer and continuation metadata and must not be used as pure model-state costs. Every D-logit tensor has shape 31,952 × 11, and all 21 receipts have the same exact D episode order and D label-array identity. The largest absolute difference between recomputed and recorded D macro-F1 is **1.1102230246251565e-16**.

`evidence/LEDGER.json` binds each selected model to its checkpoint, D logits, original result report, canonical configuration, per-tensor manifest, source map, D manifest/order/labels, recorded runtime fields and native observation receipt. Missing producer runtime fields remain missing; they are not inferred from the reader runtime. The complete tensors and D payload remain in the original operator artifacts; this repository carries their exact byte identities and the detailed read receipts.

| Selected model | Strict-best epoch | Recorded D macro-F1 | Checkpoint SHA256 |
|---|---:|---:|---|
| gru-s101-lr0.003 | 52 | 0.432333687576794 | 298f02990997e52415c639b6de31a5b310335c66772d84044b2ed98da463be2a |
| gru-s211-lr0.003 | 38 | 0.412045158200705 | 52ccfebae7af4a6f61e389bddda37e7b906c0450d6017e4e0c969630abd16747 |
| gru-s307-lr0.003 | 77 | 0.430545394996418 | 8741042107ca31f1b5d883b383f6ddd4e192e92b7d01931d613ca8c296a26bbf |
| cfc-s101-lr0.003 | 56 | 0.360341671056930 | 37b9610f174a6dccdd929e2928aba51c4f9b30a555e01699ee139949161b9106 |
| cfc-s211-lr0.003 | 34 | 0.330601609765483 | cbf266ef3df4ae572b8e64e0410319fada7b37f84355b77a16a3050207bfe178 |
| cfc-s307-lr0.003 | 38 | 0.356131950741859 | 83229524be1df8364203da1f1ab5d715ce429273f35e5cc1155a0c0d5f52eb5c |
| snn_plif-s101-lr0.003 | 31 | 0.169317782490385 | c951174dc1bcb185e8ff31087b4f9b057ecb9107a2ca3374d2e0210d8a558131 |
| snn_plif-s211-lr0.003 | 26 | 0.112659369581008 | 3ebdbf576b67a2e99ca9c0da1cc737d2fd37491baa185a4f42decf3a44d1c69b |
| snn_plif-s307-lr0.003 | 41 | 0.167958933583199 | 2ebd7d23160eaacf91934b6a7a71827928aa1ea187cd76c57478004056ca7149 |
| event_time_lif-s101-lr0.003 | 88 | 0.360944859186322 | 71a94bbbed57941025e0d0ec15b5e472789efc1bd3d33e80f3d7a500d18b1c4c |
| event_time_lif-s211-lr0.003 | 42 | 0.295065882624745 | 68df54a2398aad21883b9c228e632fcbeafe9a0dc37fb29e887ff24ff7e1c2ff |
| event_time_lif-s307-lr0.003 | 77 | 0.283080820711016 | 7673970ecb8f0a2546cc85fc4293ad3c1bb3314aa857edea0f557d489d03f347 |
| ssm_s4d-s101-lr0.003 | 78 | 0.347751174138446 | 34dda39e21c0e916c8d4c47d88cc0b7f478945fe88f70993fbed15d0d5749dae |
| ssm_s4d-s211-lr0.003 | 139 | 0.394161859511397 | 47aea1b3530c6a15a1048a1c8d408a4e555575a301c53147e37d01493f1345e6 |
| ssm_s4d-s307-lr0.003 | 85 | 0.358683799016770 | 83a91f6756cbf32b52e868a481f8f29ba29fb7428130c71e394cf7be99dd1b25 |
| attention-s101-lr0.003 | 65 | 0.432450292371103 | 0c407a14771f0df030dca1508993ec9db62e868d478f97b051cca88c023cae95 |
| attention-s211-lr0.003 | 34 | 0.346441041484619 | 54a17f3d0d805d84d7417877d52ee7414e93016dd5894f3779f3bc8a1db11685 |
| attention-s307-lr0.003 | 73 | 0.428958233490700 | 2070bf2ca292a82e8b20af95bc74ffa78ec7c64226d16b38e44ffd0a963838d7 |
| hcsn-s101-lr0.003 | 74 | 0.387834259657795 | 6855ea465862d256fc64808f64bee382ed2eea5e68367bc63025f3d238fc51f8 |
| hcsn-s211-lr0.003 | 40 | 0.391093236145486 | e04f89af1ee3e0e0d015217eb3737c8db980b96f3f93535f67134044622f191c |
| hcsn-s307-lr0.003 | 62 | 0.349830588864113 | a98c97740fe3eff04fd3f05f76aea3301e3e59b06ad0e68a094bd1d6161268fe |

### Authentic checkpoint path reconciliation

The initial inventory matched all 18 baseline selections and preserved three rejected HCSN best-path aliases. Final original C2 commit receipts identify the true selected targets. A supplemental reader verified the epoch-74 seed-101 and epoch-62 seed-307 checkpoint files without repeating the 18 successful reads. Seed 211's `inherited-best.pt` path was also unavailable or nonregular; that failure remains preserved. The original parent run's `campaign-v2/hcsn-s211-lr0.003/best.pt` has exactly the inherited epoch-40 checkpoint SHA `e04f89af1ee3e0e0d015217eb3737c8db980b96f3f93535f67134044622f191c`, so a final single-target reader closed that path gap without choosing a different model or epoch. The old aliases were not repaired or followed.

The selected S4D seed-211 .003 model comes from the original C1 continuation. Its prior absence of a direct resume-start witness remains a limitation; this checkpoint inventory does not erase it.

### Exact source aliases and runtime limits

Of the 88 expected original source paths, 80 were readable and matched. The remaining eight historical `/data/.../torch/nn/modules/` Python files are preserved in `evidence/recovered-source/`, with an original-path-to-actual-artifact map in `ALIASES.json`:

- `activation.py`, `container.py` and `linear.py` were recovered from the original PR #6214 archive at commit `917e4886658ae9f0c342eb1fa0f545d79c39e2c8`, archive SHA `37d387507ec150abfdad4065c23612e18fca6643d489f3555874c8e57a514b75` (11,397,159 bytes).
- `conv.py`, `dropout.py`, `normalization.py`, `rnn.py` and `transformer.py` were already present in the local Torch installation. Their full file bytes match the original historical SHA256 identities exactly. They were copied as evidence without rebuilding or editing the source.

All eight are exact byte matches, not approximations or source reconstructions. Unsuccessful searches of the original #6747 archive remain in the record. These Python copies do not restore the historical cu128 compiled runtime or prove environment equivalence. The reader used Python 3.12.3, Torch 2.8.0+cpu and NumPy 2.3.5, with no model computation. A future evaluation still needs its own frozen runtime and admission. Third-party Python files here are immutable evidence objects, not newly authored implementation modules.

## Metadata contract and validation

`scorer_contract.py` validates a label-free feature-manifest metadata schema and all 21 prediction-receipt metadata entries against the selected model bindings and exact row-order identity. Unknown feature roles, changed model/order hashes, missing or duplicate predictions, nonpositive or boolean byte counts, and predictions not completed before label access are rejected. Its result is a content hash of metadata: it is not an author signature, proof of payload bytes or custody, or permission to access labels.

The 15 focused controls include the actual 42-to-21 selection, exact-tie policy, retention and blocking of a higher-mean inadequate winner, and synthetic prediction metadata rejection. Those synthetic fixtures do not contain or represent E results. Their original source hashes and measured scope are in `evidence/CONTROLS.json`.

An independent read-only review examined `build_selection.py`, `finalize.py` and `scorer_contract.py` and found no blocking issue with the current fixed selection. It identified a maintenance issue in the finalizer's hardcoded aggregate adequacy field. The field now derives from the actual 21 selections. The finalizer also checks each native reader/request/source-record identity explicitly. A subsequent `finalize.py --verify-existing` invocation recomposed and compared both output artifacts byte for byte without writing or changing them; the ledger SHA remains `5e3e64f332d9a03389c8ac0e4f3de478e9f7c612124e9bec2b4d82c21d3f263b`. The pre-native frozen builder, inventories, requests and original selection bytes remain unchanged.

## Measured cost and retained failures

| Native read-only job | Matched new targets | Main-body wall seconds | Main-body CPU seconds | Peak RSS KiB |
|---|---:|---:|---:|---:|
| `1a1f3896ecf-ffbe-d85` | 18 | 4.081034067028668 | 2.867870224 | 221868 |
| `1a1f38cf40d-ffbe-d8c` | 2 | 1.783718231949024 | 1.754019930 | 219976 |
| `1a1f3902a37-ffbe-d94` | 1 | 1.919584082963411 | 1.824593304 | 218488 |

Main-body sums are 7.7843363819411024 wall seconds and 6.4464834579999994 CPU seconds. The timers include NumPy/Torch imports inside each reader entry point but do not capture the complete native-process startup, transport, orchestration or source-recovery lifetime. They are read-only postprocessing costs, not new training costs. No old budget is refunded or reset. Original 42-fit/C1/C2 cost records and unknown intervals remain separate.

All launch, terminal and stream receipts are retained. The initial oversized `h_process_list` error, rejected aliases, no-match source scans and one incorrect-path source-record read are also retained; they are not interpreted as evidence of process absence or overwritten by later success.

## Exact remaining E artifacts and admission

`evidence/SCORER_INPUT.json` is an unexecuted input contract with null feature, calibration, prediction and label artifacts. The precise remaining material is:

1. All 21 D temperature-optimization receipts under the original bounds and solver.
2. Separate hashed E-only feature and label artifacts, with exact row order and demonstrated custody separation.
3. All 21 complete immutable prediction artifacts and receipts frozen before label access.
4. Final source/runtime/checkpoint/selection/budget admission satisfying the original E proposal, including its independent audit and old-controller/full-training conditions.

The original proposal is `qualification/hcsn_differentiable/evidence/p0p5-c2-progress-20261110/confirmation-E-proposal/PLAN.json`. Its contents were consulted as metadata; no E payload was read. This change closes the D roster and artifact-identity gap only. The original full-training replay, controller, numerical qualification and E confirmation gates retain their own results and criteria.

## Reproducibility and review stages

The namespace builds on parent #6751 head `865e8f4960577f7e4774aa6c24df85fe5b3d5cb6`. The first source freeze binds the builder, initial reader, request and selection before any native inventory. Separate supplemental freezes preserve the exact rejected-path reconciliation sequence. The first ledger and scorer-input output files are immutable. The finalizer's read-only verification entry point is:

```sh
python qualification/hcsn_c2_d_selection_20261119/finalize.py --verify-existing
```

The review stages separate (1) the selection and frozen initial byte inventory, (2) the metadata-only finalizer/contract/controls, and (3) mechanical supplemental reader copies, generated evidence and exact third-party source copies. The bulk of the diff is original observations or mechanically preserved evidence. No production neuron, training, baseline or prior qualification source is modified.
