# P1/P4: independent original Group V2 three-seed summary audit

**Research-only / DRAFT / DENY_ALL.** This additive child of original real Granite97 V2 research [PR #2271](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2271) starts at `16fbbf2b5ab2d29b03eb605e8a797e1f16402ae0`. It makes **no changes** to the original source, learned Cell core, Reader, actual pretrained model, original experiment arrays, split selection logic, native Q32 or NDU owner. This is a second independent **arithmetic program over original committed metadata**, not a re-running of the offline 2.66 MB original raw evidence ZIP.

## Precise original source and costs

Original committed file `qualification/stem-cell-v1/GROUP_REASONING_V2_3SEED_20261015.json` has exact Git blob `e2913669e502238c82c7f8982ead99d7998e99c7`. It summarizes seeds 41/47/53, all eight study arms, 96 original test cases per seed/arm (288 combined), and 120 actual training updates per seed for four trainable model variants. The offline original raw evidence ZIP is referenced by SHA256 `692283c5bd54793348c701fbb115e6dc33e2625109ad0da0bee7fa9576641d96`, but is **NOT included, downloaded, or independently examined by this PR**. Neither a Git blob hash nor self-reported native replay proves original model publisher/host authenticity.

A second arithmetic implementation recomputed these totals **directly from the pinned original GitHub JSON**:

| Original arm | Correct/288 | Actual reasoning steps | Observed online CPU seconds |
| --- | ---: | ---: | ---: |
| Static Head | 31 | 288 | 0.918265 |
| Wide Head | 28 | 288 | 0.888364 |
| Fixed recurrent | 26 | 1152 | 5.013471 |
| Adaptive gate | 26 | 638 | 4.716051 |
| NDU | 26 | 288 | 2.710874 |
| No verifier | 26 | 1152 | 4.745947 |
| Reset state | 26 | 1152 | 5.028818 |
| Split candidate | 31 | 1152 | 6.209836 |

All three original split candidates were **rejected**. Against the static Head, Split's exact original observed online CPU is **6.762576209×**, no accuracy change; NDU is **2.952170064×** with five fewer correct. The original Encoder receipt records 2496 logical feature requests but 2267 physical forwards, a 229-forward **mechanical request-count** reduction; this does **not** establish equivalent/cached semantic learning or total system speedup.

- Training CPU totals: Static 1.714725213 s; Wide 1.609054376 s; Core 15.512212662 s; Split 20.125029019 s, with four sets of 360 actual updates combined across 3 seeds. These cannot be added blindly to online CPU and called a controlled complete-lifecycle comparison without original physical amortization and critic/Encoder work distribution.
- Original model remains selected as `core` under the original validation-only split gate, **not** because the original held-test was used to promote it.
- Encoder cumulative load/encode CPU 340.021368293 s; incomplete `aten.silu.default` means full FLOPs are unknown. 599,591,224 "cache canonical bytes" are not physical RSS. All per-case online CPU measurements exclude model loading/feature amortization, training and critic fitting.
- Eight-class task test rates are low, near chance. This does **not** demonstrate robust reasoning or transferable natural-task future efficacy, and three seeds do not constitute three independent source families.

## New executable independent audit

`group_v2_independent_negative.py` checks exact original Git blob and SHA-pinned archive **reference**, the 10 original source module SHA identities, same frozen source across all three seeds, all eight alternative test arm 96-sample/status/step counts, independent sums vs original declaration, valid p50/p95/CPU sample scope, 360 updates/model over 3 seeds, real requested vs physical Encoder-forward counts, missing operator FLOPs, source-specific no-GO and authority false.

`test_group_v2_independent_negative.py` has 11 strictly original source JSON-backed test methods (including tampering, impossible sample counts, changed model SHA/retained split, false NDU improvement, fake FLOP coverage, missing seed and forged aggregate). New read-only Actions exact source-HEAD and synthetic-merge workflow requires **actual execution**, rather than inheriting original hosted queued checks. Its expected source pin is the original commit/object, not a label-bearing archive snapshot.

### Executed/remaining
The independent JavaScript/GitHub connector replay of all 3 × 8 original test totals and 3 × 4 training summary slices **completed** and matched the original aggregate for all tested fields; original source HEAD Git SHA was fetched, with verified source identity. The submitted new Python code and test were remote-readback verified; **new Python CI is not claimed passed until an actual completed run exists**. The original offline raw evidence ZIP and publisher-signed model verification are outside the scope of this child.

Mandatory next steps: obtain and independently review the actual 2.66 MB raw evidence file with source/label/weights hashes; target-host whole-pipeline costs, future source families and explicit retention, balanced matched-compute experiments with an independently scored teacher. All `DENY_ALL`, `production_accepted=false`, no model selection, no NDU activation, no 10T/100T equivalence, no `main` merge.
