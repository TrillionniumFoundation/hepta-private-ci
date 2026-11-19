# HPCA V2 retained-adapter actual-weight diagnostic — HOLD_NO_GO

## Precise scope

Read-only numerical audit of the original retained adapter safetensors from PR #5905 (exact head 0ed4fce8bd07d361bf7eba40c40fe73d1f349c66). No additional model training, evaluator, independent future B, production Owner or deployment was executed. Matched four-seed B/C binary accuracy was identical between arms; this cannot establish weight equivalence.

Checkpoints are retained on the authorized ai395 research host, NOT redistributed in this PR. The script supports HPCA_V2_ARCHIVE_ROOT for authorized replay. Github CI without the archive is limited to parser/unit tests; the original-archive test skips explicitly.

Source archive RESULT sha256: 9512849b90964c35951bb8bb2226b3f2f6d3ec0da1e9a3b98467c8970afbe39c
Original V2 training executable sha256: 4dded105ac0477c9747b13d98ee1b57d46dcc322d034121a55a9c63a12250e5e
Original frozen V2 plan sha256: 08677c300eff2e66807b19529728dbf9b7b1e8bd43fa265949763261f7bca6af

All 8 original checkpoint SHA256 and byte sizes are checked against the original per-run checkpoint_files receipts, before parsing. Tensor keys and shapes, F32/finite data, bounds and contiguous offsets are checked. Actual byte values, not only hashes, determine the measurements.

## Actual retained tensor contrasts

| Seed | Early group (layers 0-14) paired L2 | Late group (layers 15-29) paired L2 |
|---:|---:|---:|
| 11 | 0.035930534344 | 0.025791184085 |
| 17 | 0.023569382185 | 0.027434260719 |
| 23 | 0.016148277226 | 0.053330842247 |
| 29 | 0.019659939442 | 0.031021289028 |

Early group paired RMS ranges 6.1422053e-05 to 0.000136666418; late group 9.8100092e-05 to 0.000202850731. Both groups have nonzero pair differences for all four seeds. Thus actual retained parameter values diverge under differing update orders despite equal exposed binary-task accuracy. No independent usefulness inference follows.

## Resource and qualification record

Read-only analysis wall seconds 0.162722, process CPU seconds 0.162706, RSS peak KiB 20048. These do not include already recorded V2 training costs and do not measure power.

Replay commands from this directory: python3 -m unittest -v test_hpca_v2_retained_weight_audit.py ; python3 hpca_v2_retained_weight_audit.py > REAL_CPU_V2_WEIGHT_RESULT.json (original archive must be available). Original archive tests are skipped when absent. Numeric process times naturally vary.

Limitations: 4 selected seeds, B and C exposed/operator-written; no independent evaluator, no actual ACT/CTRL feedback, seven-lineage effects, owner adoption, NDU four-arm causal attribution, production effect, old task/OOD, independent future B/C, or cold owner recovery. Parameter divergence is a mechanism diagnostic, NOT scientific utility or production qualification.

Decision: HOLD_NO_GO / DENY_ALL. Draft research evidence only; no merge/deployment/authority escalation.
