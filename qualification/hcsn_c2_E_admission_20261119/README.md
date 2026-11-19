# C2: recovered runtime, six current-best D replays, and retained E gates

## Outcome

All **six current strict-best HCSN checkpoints** now pass a complete D forward under the recovered original Python and Torch payload. Each checkpoint ran one successful forward over all **128 windows / 31,952 events**. Fresh and saved logits have **maximum absolute difference 0**. The independently downloaded tensors reproduce every recorded metric within **2.220446049250313e-16**. No training, backward pass, optimizer operation, E inference or E scoring was performed.

This result closes the current-checkpoint full-D reproducibility gap. It does not establish an original full training replay: that count remains **0/6**. The original controller terminal remains **UNKNOWN**, and the original complete chain/trace/cost auditor remains incomplete. E admission therefore remains **HOLD** under the unchanged original conditions.

The machine-readable entry points are [FINAL_READBACK.json](FINAL_READBACK.json), [FINAL_SUMMARY.json](FINAL_SUMMARY.json), [E_GATE_REVIEW.json](E_GATE_REVIEW.json), and [SEALED_SELECTION.json](SEALED_SELECTION.json). Full frozen programs, manifests, native job receipts, failed attempts, batch logs and six complete fresh tensors are retained in the three original ZIP archives below. Readable files outside the ZIPs preserve their original bytes.

## Six complete D results

| Seed | LR | Strict-best epoch | Fresh independent D macro-F1 | Max absolute logit difference | Checkpoint SHA256 |
|---|---:|---:|---:|---:|---|
| 101 | .001 | 106 | 0.3440169977772091 | 0 | 9334f1c0aa990005c87bcb303fda7b27e59376ac10f58d39ba3b33ed297449fa |
| 101 | .003 | 74 | 0.38783425965779494 | 0 | 6855ea465862d256fc64808f64bee382ed2eea5e68367bc63025f3d238fc51f8 |
| 211 | .001 | 144 | 0.388353751030186 | 0 | 83f7b3148c10fa377feb9f4449ffa42a0b1679f073569f1886852d7eb82145c3 |
| 211 | .003 | 40 | 0.3910932361454862 | 0 | e04f89af1ee3e0e0d015217eb3737c8db980b96f3f93535f67134044622f191c |
| 307 | .001 | 126 | 0.33231907785802234 | 0 | 14a9c527bf87ad6524c771ab7da5a1ccf32723cd1f2fc6c7d8f6d8797d1b2ed9 |
| 307 | .003 | 62 | 0.3498305888641129 | 0 | a98c97740fe3eff04fd3f05f76aea3301e3e59b06ad0e68a094bd1d6161268fe |

The corresponding three-seed means are **.35489660888847246** at .001 and **.3762526948891313** at .003. D was used for training selection; these values are development evidence. They do not show a held-out advantage over other architectures. Last-place differences from historical rounded/recomputed F1 values are retained in the reader's per-metric error fields.

The frozen result field `bitwise_saved_logit_match` was implemented using `torch.equal`. It establishes exact numerical equality together with maximum absolute difference 0, but does not distinguish positive and negative zero bit patterns. This report therefore makes no bytewise-logit claim. Frozen producer fields were not renamed or rewritten.

## Exact runtime restoration and independent readback

[The runtime restoration evidence](../hcsn_c2_original_runtime_recovery_20261119/README.md) binds the original Python **3.12.3** executable SHA256 `e50d468e8b0adfb05733f5b87b3cff34829c4a8c1aea50c865aa8bdfe4bb150f` and verifies **12,672 nongenerated RECORD-bound payload files** from six original packages. The forward runtime uses Torch **2.8.0+cu128**, NumPy **2.3.5**, float64 CPU evaluation, batch size 32 and one CPU thread. The isolated recovered venv leaves the old environment untouched. Exact unrecorded system libraries and historical package metadata are not claimed; installation paths and generated metadata differ and remain explicit.

The final archive reader ran locally with Python **3.12.14**, Torch **2.8.0+cpu** and NumPy **2.3.5** solely for `torch.load(weights_only=True)` and independent NumPy metric recomputation. It constructs no model and performs no forward. [READER_RUNTIME.json](READER_RUNTIME.json) binds its executable, reader source and result. This CPU reader is not substituted for the original cu128 scientific runtime.

All **17,124,424 ZIP bytes / 161 members** were checked against whole-archive and per-member SHA256 identities. Version-pinned native reads also checked every returned chunk. The reader verifies every full-array label hash, episode identity, event position, checkpoint/epoch binding, zero-update receipt, unchanged input/model hash, complete six-candidate coverage, original caps and absence of repeated successful forwards. Its first execution passed. Its measured **function body** took **2.9404070980 s wall / 2.9176498290 s CPU**, peak process RSS **228,560 KiB**. The body timer includes Torch/NumPy imports made inside `run`, but excludes interpreter startup, preceding module imports and final report output.

## Three frozen scientific phases and five retained failures

| Phase | Frozen source commit | Native job | Native terminal | New successful forwards |
|---|---|---|---|---:|
| Original current-D request | `6e53707e317f6d0a12d5402ac9dd14c26dc3ae4c` | `1a1f3ec2f5e-ffbe-e7f` | failed, exit 2 | 3 |
| Exact initialization-path reconciliation | `9d4366cba399dff877879cc8f6ac03e0f3a1ba67` | `1a1f3f499b2-ffbe-e8d` | failed, exit 2 | 1 |
| Original-plan configuration-index reconciliation | `6665a66ebdae1224d8a6bac4f22c0878136b33f7` | `1a1f400819b-ffbe-eac` | succeeded, exit 0 | 2 |

All three terminal receipts confirm complete, durable, untruncated output. The original request passed three candidates; three others failed before model construction because their old initialization paths no longer existed. The second phase bound surviving files with identical original SHA256 and byte counts, preserving old paths and failure records rather than filling old directories. Only the three never-forwarded candidates were admitted.

That phase passed seed 101 at .003. The two .001 continuation candidates then failed the unchanged strict checkpoint-semantics guard. Read-only diagnostics showed that checkpoint epochs, data identities and actual configurations were correct, but the earlier all-42 selection index left these two `model_configuration` fields null. The selected 21-model .003 roster was unaffected.

The third phase derived expectations from each SHA-bound original parent plan using the original construction function, then required equality among the parent report, plan-derived construction, original initialization and new request before any forward. Only the missing configuration-index field changed. The original checkpoint bytes and `replay.py` semantics guard remained unchanged. The two remaining candidates then completed their first successful forwards. [The independent path review](independent-reviews/C2_ALIAS_REVIEW.md) and [configuration review](independent-reviews/C2_CONFIGURATION_REVIEW.md) preserve the separate pre-execution review evidence.

The original three missing-path failures and two null-index failures remain in the original ZIPs and [FINAL_READBACK.json](FINAL_READBACK.json), with their own result hashes and costs. There was no successful-forward retry, candidate replacement, learning-rate change or budget refresh. The first source-delivery attempt failed before execution with exit 127; a second transport launch remains unknown. The final delivery used a create-only shared execution directory, so the late uncertain delivery cannot duplicate a scientific run. These transport observations remain separate from the scientific five-failure count and from the historical controller's unknown status.

## Costs and caps

The original absolute deadline remained **1795095504.542**. Creation of the first actual native current-D job to final archive creation took **1617.8239147663 s**; creation to the last confirmed native terminal took **1617.896 s**, both within **1800 s**. These calendar durations include intervening orchestration. The original per-fit **210 s** and metadata **360 s** allowances deducted all earlier failed attempts and the independent metadata diagnostic before recovery. No allowance was renewed.

| Candidate | Attempts including preflight failures | Cumulative child wall seconds | Cumulative child CPU seconds | Maximum child RSS KiB |
|---|---:|---:|---:|---:|
| 101 / .001 | 1 | 125.0951391140 | 124.494502 | 885,516 |
| 101 / .003 | 2 | 126.4019654890 | 125.883236 | 888,292 |
| 211 / .001 | 3 | 138.9224092201 | 137.888402 | 883,372 |
| 211 / .003 | 1 | 145.5268917000 | 145.159749 | 885,284 |
| 307 / .001 | 3 | 139.5249571200 | 138.636101 | 874,476 |
| 307 / .003 | 1 | 142.4238842200 | 140.708310 | 888,328 |

All **14 wait4-measured children**, including original-chain metadata and configuration proof, total **852.2501268770 child wall seconds / 838.057776 CPU seconds**. Their maximum child peak RSS is **888,328 KiB**. The six candidates' eleven attempts account for **817.8952468630 wall / 812.770300 CPU seconds**; the three metadata children account for **34.3548800140 wall / 25.287476 CPU seconds**. An external zero-forward diagnostic charged its full **6.838 s native creation-to-terminal duration**, so the metadata pool consumed **41.1928800140 s**; that diagnostic's CPU time is unknown, not zero.

Child timers are nested in native elapsed time and must not be added again to that elapsed time. [FINAL_SUMMARY.json](FINAL_SUMMARY.json) retains every child and all native intervals. Runtime restoration, prior calibration, subsequent transport/publication and final local readback have their own scopes and are not silently included in the 1800-second scientific timer. This diagnostic evidence does not establish isolated steady-state inference cost or equal-budget architecture superiority.

Each HCSN model state_dict contains **146,280 tensor bytes**. Complete recurrent density, content and delay-state bytes remain **unmeasured/null**; model weights are not reported as complete neuron state. Historical missing CPU/energy/VRAM/money and unknown controller intervals remain unknown.

## Original checkpoint/optimizer continuity: what is proved and what is missing

The surviving original artifacts prove **6/6 resume-start full model + AdamW + RNG witnesses** against their parent checkpoints. Auditing constructs/restores no optimizer. Across the six original chains, **289 completed-epoch commits** have matching artifacts and **zero commit-validation errors**. The four original terminal fits have no remaining failures in these surviving-chain checks.

The two original .001 fits still lack authentic producer terminal reports and finished journal events. Seed 211's original journal has malformed line 3075 and lower bounds of **970 completed / 971 started optimizer calls**. Seed 307's journal has malformed line 3114 and lower bounds of **983 completed / 983 started optimizer calls**. These are partial-work observations, not reconstructed exits. They do not overwrite the later independently archived continuation results or relabel current bests as original complete traces.

[The exact known-controller lookup](ORIGINAL_CONTROLLER_OBSERVATION.json) again returns job `1a1c74f3308-be2a-75` with outcome `unknown`, `status_authoritative=false`, and the reason that its supervisor disappeared without a confirmed terminal receipt. No broad process search, inferred exit, fabricated terminal, or post-hoc zero cost is used. Missing original paths remain:

- `/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training/c2-native-execution-20261110-c385-v1/RESULT.json`
- `/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training/c2-native-execution-20261110-c385-v1/fits/hcsn-s211-lr0.001/result.json`
- `/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training/c2-native-execution-20261110-c385-v1/fits/hcsn-s307-lr0.001/result.json`

Original full-training replay remains **0/6**. Surviving commit/witness checks and six current-best forwards do not by themselves constitute the original full chain/trace/partial-work/cost auditor.

## Calibrated selection and E admission

The existing [D-temperature results](../hcsn_c2_d_temperature_20261119/README.md), Draft #6759, contain **21/21** completed temperature optimizations. All selected temperatures reduce D NLL and preserve argmax predictions. [SEALED_SELECTION.json](SEALED_SELECTION.json) binds all **21 models and 21 temperatures** to original checkpoint, configuration, source, D-order and calibration receipt identities. Its exact SHA256 is **`6c20a236747ec5733643a68e1761fdcdb31e186643d89b2ab4ae8e615d3531b6`**. No choice was made using E.

[E_GATE_REVIEW.json](E_GATE_REVIEW.json) preserves all six necessary conditions verbatim from the original E proposal and binds that plan's SHA256. Current D quality and recorded selected-model adequacy are now concrete. The original authentic-terminal condition and complete-independent-auditor condition still fail. Current global user authorization does not supply the missing historical evidence; there is no invented external-owner requirement or newly opened diagnostic E path. E payload, labels, predictions and scores remain unopened in this work, and no E automatic trigger is introduced. Legacy schema exposure recorded in the original proposal remains acknowledged; this is not a retroactive claim of complete historical feature/schema blindness.

## Original archives

| Archive | Bytes | Members | SHA256 |
|---|---:|---:|---|
| [Original current-D delivery](../hcsn_c2_current_D_replay_20261119/evidence/native/originals.zip) | 8,492,120 | 60 | 16ec51e3480048b0e19a59ac85d4a5a4a8188d37624453c257f01cfb1513bafa |
| [Exact initialization reconciliation](../hcsn_c2_D_path_reconciliation_20261119/evidence/native/originals.zip) | 2,952,963 | 48 | 79cebc33bd0d70daa51cc076d7a3faf79c7e664a43dcb3215d44b941c984f8e2 |
| [Strict configuration reconciliation](../hcsn_c2_D_configuration_reconciliation_20261119/evidence/native/originals.zip) | 5,679,341 | 53 | 3a59a535c78ef88d07940876cc606bc13f5a9c27d3bb247cdaff812375d4c9c2 |

The final readback SHA256 is **`2d7657124c366eff56d2afc8cbc0f3289d054c4de4dbd779558f681323bc53d7`**. Source freezes were published before each native execution. This evidence addition does not modify those frozen programs, previous results, model checkpoints, initialization files, training budgets, the original E policy or production code.
