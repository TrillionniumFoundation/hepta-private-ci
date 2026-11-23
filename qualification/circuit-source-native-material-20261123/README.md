# Native component identity review

The two-phase offline evaluation used Circuit `32ee053d020918d0a694c8b9a3a3bcaec3dfd93eed5bb7f98e0b33e46352dac4`. Its source Cell loads a GPT-2 output-head LoRA. This review reads its actual adapter weights back into the local predictor, checks both factor tensors against the values in memory, replays the trained input on the parent and child and verifies the two-phase evaluation against its separately retained commitments. All tasks in this experiment are authored fixtures.

| Material | Native operation `learning-d9fb-native-adopt-v1` | Circuit source Cell |
| --- | --- | --- |
| Adapter file SHA-256 | `56d88f2dda61db06f88a96ebed05d29e1a9e2e8d1d02e3f296a8544df743e45c` | `1bd54e3b301598ee45b6c6103aef57aedb93b746bdcbc9b2be4af05cd153ae9a` |
| Target and rank | 60 query/value projections of width 576, rank 4 | One output head of width 8, rank 1 |
| Physical tensors | 120 LoRA factors | Two LoRA factors and the saved base output head |
| Version identity | `8c650b9ad74f5b8ec152d700ce184b30bf3cdf008a6b27b2eacbd0805d30f308` under the native Cell descriptor codec | `42ccc5cf900ffd80fbc78fb5c8ab90c8c9553edb0bbfba09e327e3ec375862ff` under the coding_sft manifest codec |

The original HEPLCP02 initial and terminal checkpoints decode as seven native learning stages for the historical operation. Its selected descriptor binds the adapter wrapper and insertion contract through separate domain-separated hashes. The local Circuit source's parameter-state digest recomputes to `125a8276376c2c9813d74df9fb4797bb4ecc33438b39ec3beec453b9b3bb3af9`, matching the one-step SGD receipt. The raw two-phase result has file SHA-256 `71ab38f3cbbfe6cb6e259f52a6db7cef564c244e9c901f64b506c2d76c22435c`.

## Native producer boundary

At Hepta commit `1df26bf88c32a7c61340f1c1a93ae88d7841509b`, `codex-rs/hepta-agentd/src/learning_iteration_research_external_material.rs` checks actual model bytes and the fixed SmolLM contract in `verify_material`. Its `freeze` and `require_unstarted` functions bind the original research owner before training and the fixed evaluation protocol. The generic `LearningIterationCheckpointOwnerV1` persists receipts supplied by registered stage owners. The normal parameter and topology proposal routes require their generator and evaluator attestations. The external trained-artifact research route is test-only and implements the fixed SmolLM profile.

To cover this Circuit, a scoped native owner would need to freeze its own initial operation before training, verify the Cell factors and insertion interface, bind both Cell manifests and the frozen router, preserve the protected predecessor through selection and record the subsequent actual use. The native Cell component schema has a composition digest but defines no reader for this Circuit bundle or its router and graph semantics. The recorded native checkpoint count for the tiny candidate is zero. A separately funded evaluation-service run can be accounted for independently of this full learning operation.

## Reproduction

Use the locked CPU environment from the paired-cold experiment, the Hepta checkout including the Circuit evaluator and the historical Chain evidence checkout at `c27f48940e7521e7cdb1851fd8b652ca4a4f5b5a`. Pass the extracted controlled model run for `MODEL_RUN` and the offline two-phase output for `EVALUATION_RUN`. Record hashes and all four task outcomes are included in `RESULT.json`. The output is create-only.

```bash
PYTHONPATH="$HEPTA/scripts:$CHAIN/scripts" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python \
  "$HEPTA/qualification/circuit-source-native-material-20261123/compare_native_source.py" \
  "$MODEL_RUN" "$EVALUATION_RUN" \
  "$CHAIN/evidence/hepta-real-native-adoption-20261108" \
  "$NEW_REPORT"
```
