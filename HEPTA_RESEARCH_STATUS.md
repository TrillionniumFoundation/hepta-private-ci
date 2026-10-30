# Hepta research status — verified recovery release

The executable shared-boundary Call–Put prototype, fixed-checkpoint study, recovery verification and public evidence release are complete for the scope documented here. The central scientific result is **0 of 24 registered metric-improvement gates passed**. The analytic operator was trainable on the two synthetic memory tasks; this study did not establish a performance or cost advantage.

Public disclosure of this round's code, checkpoints, raw data and evidence to `TrillionniumFoundation/hepta-private-ci`, branch `research/hcsn-callput-rebuild-20261028`, was explicitly authorized. No publication permission remains outstanding.

## Canonical deliverables

- [Readable recovery report, with embedded figures and complete tables](research_evidence/hepta_stable_flow_20261029/report003_recovery/Hepta_Recovery_Scientific_Report_20261030.html)
- [Complete machine-readable recovery report](research_evidence/hepta_stable_flow_20261029/report003_recovery/report_summary.json)
- [Report binding: 754 inputs and 7 outputs](research_evidence/hepta_stable_flow_20261029/report003_recovery/report_receipt.json)
- [Final recovery audit](research_evidence/hepta_stable_flow_20261029/recovery_20261030/final_recovery_audit.json)
- [Complete recovery archive parts and individual hashes](research_evidence/hepta_stable_flow_20261029/releases/recovery_parts_20261030/PARTS.json)
- [Independent extraction and real reconstruction audit](research_evidence/hepta_stable_flow_20261029/releases/independent_recovery_archive_audit.json)
- [Exact-commit public byte readback](research_evidence/hepta_stable_flow_20261029/releases/public_recovery_parts_readback.json)
- [All 1,170 committed scientific files compared with the archive manifest](research_evidence/hepta_stable_flow_20261029/releases/public_scientific_tree_readback.json)

| Release identity | Value |
| --- | --- |
| Scientific evidence commit | `fc7d141c19703e7e104cff2a8dae5c492f034a77` |
| Archive-parts publication commit | `5a2dd4945fc04785ec142920dc28c5042666211f` |
| Archive filename | `hepta_recovery_evidence_20261030.tar.gz` |
| Archive bytes | **18,821,020** |
| Archive SHA-256 | `604c2e402a1bba5c15121e9a1165a59e58e4a4322da87f73086500d7a5256423` |
| Evidence files | **1,170**, plus the manifest |
| Uncompressed evidence bytes | **35,438,067** |
| Public parts | **9** |
| Public readback receipt SHA-256 | `170213f68767cdf678c4c89a640b4f7a25cca6ab74b8b9379fea51e7f44b5d90` |

The archive uses the distinct `hepta-recovery-evidence-v1` contract. It preserves available original files, exact digest-verified reconstructions and explicitly new numerical and timing measurements. It does not claim to be the missing earlier complete archive. Its final audit explicitly retains `all_research_blockers_closed=false` and `original_archive_recovered=false`.

## Completed experiment

The original registered training is preserved: five controller arms, two tasks, three seeds and two learning rates give **60 training candidates**, **23,040 updates**, and **300 checkpoints**. All candidates completed 384 updates and the registered CPU budget. Validation evaluated 240 eligible checkpoint choices and sealed 60 selected aliases before primary scoring. Thirty step0 identities supply the untrained control.

The tasks are selective copy and multi-query associative recall, each with 1,024 train, 256 validation and 512 test episodes, 32 tokens per episode, 16 addresses and eight value classes. Every arm shares the explicit causal role/address parser, learned content projections, matrix memory and readout. The four trainable-controller arms each have 726 trainable parameters; the frozen-parameter controller has 652 and is a diagnostic comparison. Its internal states still evolve.

### Held-out accuracy

Mean query accuracy across the three registered training seeds:

| Task and checkpoint budget | Analytic | Matched C1 | Sigmoid | Ordinary | Frozen controller parameters |
| --- | ---: | ---: | ---: | ---: | ---: |
| Selective copy, CPU30 | 20.98% | 33.40% | 74.80% | 76.81% | 75.05% |
| MQAR, CPU30 | 14.83% | 29.18% | 76.94% | 85.50% | 72.62% |
| Selective copy, update384 | 100% | 100% | 100% | 100% | 100% |
| MQAR, update384 | 100% | 100% | 100% | 100% | 100% |

At update384, all arms and seeds also achieved 100% sequence accuracy. This task saturation does not identify an analytic-operator contribution. The step0 accuracies were 11.23%–13.77%, near the 12.5% uniform baseline.

The principal analytic-versus-matched-C1 CE improvements at update384 were only about **0.000207 nat** on copy and **0.000157 nat** on MQAR. Both adjusted paired-seed intervals include zero and both effects fall below the registered 0.01 nat threshold. The analytic model did not meet the CPU30 quality floor. None of the 24 registered accuracy/CE improvement gates passed. These are exploratory three-seed comparisons with separate multiplicity families for each metric; absence of significance is not equivalence or a universal impossibility claim.

Authoritative results: [original primary results, restored to exact bytes](research_evidence/hepta_stable_flow_20261029/formal_run001/results.json).

## Numerical findings

All **24/24 end-to-end checks** passed for the fixed trained checkpoints and registered h/h2/h4 comparisons. Independent continuous-flow checks retain **7 passes and 1 failure**. The failed case is selective copy / matched C1 / seed81301 / update384: scaled state error **0.0010612751785894204**, above **0.001**. Its gradient and oracle-stability checks pass. The same state failure was reproduced without adjusting tolerances, retraining or changing selections.

The first64 test h-versus-h/2 diagnostic changed no query accuracy; the maximum absolute logit difference was about 1.2684e-4. Earlier qualification failures and the long-period untrained h=1/16 phase-probe failure remain in the record. None is erased by the successful end-to-end checks.

- [New numerical execution and all raw bindings](research_evidence/hepta_stable_flow_20261029/trained_numerics_replay_20261030/execution/summary.json)
- [Exact recovery of all 104 original numerical NPZ files](research_evidence/hepta_stable_flow_20261029/recovery_20261030/numerical_raw_reconstruction_20261030.json)
- [Mathematical analysis, periodic-orbit scope and coupling limits](experiments/call_put_stable_flow_analysis/ANALYSIS.md)

## New inference measurements

The new timing execution uses the same registered 20 seed81301 aliases, B1/B32 full 32-token forwards, three warmups and eleven timed repetitions per case. All **40 cases and 440 events** are retained. This task's other compute was paused during measurement; unrelated shared-host activity was not controlled. These are new measurements, distinct from the missing original clock records.

Eight of 16 model pairs satisfied the registered empirical quality band; all eight were update384 pairs. Across both tasks and both batch sizes, the analytic/comparator median wall-time ratios were:

| Comparator | Ratio range |
| --- | ---: |
| Matched C1 | **0.963–1.392×** |
| Ordinary | **1.904–2.653×** |
| Sigmoid | **1.870–3.471×** |
| Frozen controller parameters | **0.445–1.003×** |

A ratio above one means the analytic implementation was slower for that case. These CPU medians from one training seed are descriptive. The empirical quality band is not a statistical equivalence result, and timing repetitions are not independent model-training seeds. No GPU, energy, decoder streaming or KV-cache advantage is asserted.

The arithmetic recurrent payload is 605 bytes per episode. It excludes activations, inputs, outputs, parameters, Python objects and allocator overhead, and is not a measured cache/RAM benchmark.

[Independent metric and timing audit](research_evidence/hepta_stable_flow_20261029/recovery_20261030/replayed_measurements_audit.json) recomputes 300 primary metrics, 24 paired-t comparisons, 440 timing events, 680 timing/throughput statistics and all eligible quality ratios. It found zero inconsistencies under its declared tolerances.

## Model interpretation and remaining scientific questions

The implemented operator is a reduced perpetual-put construction, with a shared C1 boundary and Call/Put functions of the same margin. It is not the full He–Xiong rollover-debt equilibrium, and Put is not a default probability. Signed boundary feedback and a slow recovery variable support an executable ordinary BP/BPTT controller. The coupled nonlinear flow uses ETD2; it does not have an exact closed-form trajectory.

The conditional matrix-memory update is exact with fixed rates and content inside a tick. Boundary-dependent endpoint-held rates leave an outer coupling/splitting error. Internal mesh refinement alone does not establish arbitrary resampling invariance. At fixed shape the two channels observe the same scalar margin, rather than two independent state variables.

The analytic and matched-C1 arms share local boundary conditions. Their main comparison isolates operator shape beyond those shared constraints, not the causal value of free-boundary constraints themselves. Shared explicit addressing and matrix memory provide substantial task structure. This prototype is not yet a deep network transmitting only boundary messages between layers, or a general multimodal backbone.

The original five-part research route therefore has measured operator/controller, synthetic memory and CPU-cost evidence. Call-only/Put-only causal interventions, learned content addressing without supplied roles, sampling-rate/length generalization, matched native GRU/SNN/CfC/Mamba/Transformer baselines, multimodal tasks and large-scale/GPU/energy experiments remain separate scientific work. Their hypotheses have not passed by virtue of the completed engineering and publication steps.

## Recovery provenance and unavailable originals

The temporary workspace reset during publication. Recovery anchored the original report002 HTML, receipt, figures and presentation sources from uploaded Git objects. All original training checkpoints and selection records had already been public.

The primary scoring code was then run unchanged on the same checkpoints/data: **61/61 original result/prediction files matched their pre-existing SHA-256 and sizes exactly**. The numerical replay likewise reproduced **104/104 original numerical NPZ files exactly**. Two selection log files were reconstructed and verified against their original digests. Newly measured execution costs remain explicitly separate.

The original report002 now has **700 of 734 bound inputs available with exact hashes**, with **34 still missing and no content mismatches**. The missing original JSON/log/time records have not been replaced with new records under their old identities. Original report002's machine-readable summary, the original final audit, report001's missing outputs and the original complete archive are not claimed recovered. The original report002 HTML remains readable [here](research_evidence/hepta_stable_flow_20261029/report002/Hepta_New_Scientific_Report_20261029.html).

The earlier historical commit **b1806a2e2c811e7ef5b15848ba262664aa34363f** and its original weights/raw archives remain a separate recovery gap. The genuine surviving historical reports are preserved [with their exact provenance](research_evidence/hepta_callput_recovery_20261029/README.md). An original Hepta_CallPut_Followup.bundle could restore its Git objects; an original Hepta_Complete_Research_Evidence.zip could restore scientific files but not necessarily the Git commit identity. For the later interrupted publication, the missing original complete archive has SHA-256 a8ce9dccf74ff31521e736d52a238d57b689e3431f35157b451e82b4883327d8. This verified recovery release has its own identity and does not substitute for those original bytes.

## Reconstruct and verify the public archive

From a checkout containing all nine parts:

```bash
python -I -S experiments/call_put_stable_flow_analysis/release_parts.py verify --manifest research_evidence/hepta_stable_flow_20261029/releases/recovery_parts_20261030/PARTS.json
python -I -S experiments/call_put_stable_flow_analysis/release_parts.py assemble --manifest research_evidence/hepta_stable_flow_20261029/releases/recovery_parts_20261030/PARTS.json --output hepta_recovery_evidence_20261030.tar.gz
python -I -S research_evidence/hepta_stable_flow_20261029/recovery_20261030/recovery_archive.py verify --archive hepta_recovery_evidence_20261030.tar.gz
```

The output archive must not already exist. The correct verifier is recovery_archive.py; the part utility's legacy printed release.py suggestion concerns the older contract. Verification needs only the Python standard library and does not rerun training or numerical experiments.
