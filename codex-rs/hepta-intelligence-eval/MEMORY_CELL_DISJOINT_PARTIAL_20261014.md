# MemoryCell: read-only original-answer audit of 15 of 16 disjoint Qwen calibration shards

**37/40 original Qwen2.5-3B BF16 calibration calls authenticated.** This is not a completed calibration policy, a test/evaluation result, future-source evidence or a production qualification.

- Original exact [GitHub Actions run #38423223376](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38423223376), source commit `bc76ac57ba972bf105c71ddd997cd215cec5df2e`.
- Original source ZIP SHA256 `23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b`; eight-case plan SHA256 `9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`.
- Calibration-only preparation artifact ID `11827422141` ZIP SHA256 `5f4e13b23893ab64666296f565ed9884a4328f451859c0e1b10cfb4b64b19732`; plan SHA256 `66592a2dcdcb09870a057e8f2401189253e4842583b354338a1a4886a848fea6`.
- Original research-only Qwen reader identity `f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225`; canonical stage SHA256 `1b96ffaa0644f02511d0f8f1cd47f8eb4cf6bce68191220708f3ccbf592b6e2b`.

## Independently verified original calls

| Arm | Planned | Independently reopened raw generations | Missing |
| --- | ---: | ---: | ---: |
| k1 | 8 | 7 | 1 |
| k2 | 8 | 8 | 0 |
| k3 | 8 | 7 | 1 |
| k4 | 8 | 8 | 0 |
| k6 | 8 | 7 | 1 |
| **Total** | **40** | **37** | **3** |

All 37 saved calls have original successful generation status; their source selection order, complete event excerpts, recorded source content digests, original answer bytes, reader/citation request identities and source commit were verified against the original published calibration-only inputs. They contain **42,244 input tokens, 498 generated tokens and 747.577 seconds of summed per-answer inference measurements across parallel heterogeneous hosts**. Summed seconds are not wall-clock duration, portable latency or cloud billing.

**Only absent subtask:** case index 6, part 0, question `controlled_2d616eb2`, arms `k1`, `k3`, `k6`. The unsuccessful hosted job failed before inference because the AMD EPYC 7763 runner did not establish the mandatory accelerated BF16 ISA. That refusal is correct; never bypass BF16 gating, rewrite incomplete answers, or use either earlier completed 40+72 run to fill the missing three.

## Outer GitHub artifact ZIP pins (source of truth)

| Shard | Original artifact ID | Original outer ZIP SHA-256 |
| --- | ---: | --- |
| 0-0 | 11827974042 | `ad10d1d87aa3671fd347d4ca3bbe66c671a82055a58b4e9896f266ba3125fe93` |
| 0-1 | 11828136602 | `32b873bf342811ff2a40399f2502877b03174d06fec5ed017caad17602e11545` |
| 1-0 | 11828627869 | `ec13c6fc5d4dd00ba321a4f9088ca3245ddeaedd1bee8080ed0429380c540ac8` |
| 1-1 | 11828351185 | `d07af975b34f7c6d43a5c32b451af7b80478fc2942482a0dad36262c25207889` |
| 2-0 | 11828274151 | `1b57d31a6679df7cddb5aa6b6e53fe63b6066895bc0f3b102e197a213a0d4345` |
| 2-1 | 11830211593 | `72a734682ae0811e77c070d0204297c4fb01da966af7118171e7e5997b01855f` |
| 3-0 | 11829732241 | `5619331cdfa8e22f97fb680461ece6d9f78c1b1ec18622184a5fa1bdecbad058` |
| 3-1 | 11827058630 | `8f758438131e7c262cadbedd33930ed89e024a08400a5088b2d4bc17613c8c6f` |
| 4-0 | 11828171663 | `525bd94bcee18f8eb5808c4ae52aa7df06185c4fc0a9a443ac70d136e2a3a338` |
| 4-1 | 11829240794 | `25345aafd52af90035fca11dfa6f6e6b93340e47dac127362bf54aa8998fbf11` |
| 5-0 | 11829879932 | `5fb4fb42d984f340ebb285d9795ea3dac02d427e9d52c03851214eaa03702441` |
| 5-1 | 11828771883 | `3961cd0fd9a50180cd915a016210e612fc0ca583c1ad2ad3fe4d3691276c7998` |
| 6-1 | 11829716282 | `824d15c5405e5dca004aea55b71cab8a597b9c8afe1461f72890b605c0ef6aff` |
| 7-0 | 11831118634 | `101486f19014f3ee428f3acb360289d78d7a65ee42c84017916efff9d5b9d2d3` |
| 7-1 | 11829925940 | `c9bbaca2423694ed18f1f47e7282538a2cc92f4bb80a44c603f76daf6aa97bb7` |

Each original ZIP's six-member `sha-pins.json` was independently replayed and compared to its full raw-answer payload and pinned source/model identity. Original archive, calibration-only manifest and all 15 outer ZIP hashes were frozen before tamper trials. Edited raw answers, a forged emitting commit, and deletion of an expected original shard were rejected; 4 local integrity assertions passed.

## Nonpromotion and exact next gate

**There is no frozen `selected_k` in this new disjoint run.** Do not open calibration labels in the generation job until **40/40** new answers are sealed; 72 fresh nine-arm test calls and separate source-exact replay remain **0/72 / not executed** here. The previous two completed source-pinned 40+72 development runs establish a reproducible **NO-GO** for incremental graph task accuracy over the simpler full-path reader, not a permission to invent new disjoint results.

Next: use an eligible, actual BF16 host to rerun *only* case 6/part 0 and then allow exact-source calibration collection, frozen-policy selection, all 72 fresh evaluation generations, and independent immutable-source replay. Keep `blocking-ci`, source-family independence, human semantic-citation reviews, full lifecycle cost and production gates unchanged. `parametric_memory_training_qualified=false` and `production_accepted=false`.
