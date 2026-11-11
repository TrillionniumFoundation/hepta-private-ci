# HPCA V2: genuine second-process LoRA disk readback (exposed-only)

**2026-11-11 UTC: HOLD_NO_GO / DENY_ALL.** This is a new **read-only actual
PyTorch inference job**, not another HPCA training run, synthetic smoke or
a prospectively independently evaluated real-world task. It does not make
an Owner Selection, NoUpdate, Adopt, FinalUse or external effect.

## Narrow distinction from earlier evidence

PR #5905 originally ran eight actual CPU LoRA trainings, then created a
new base *object in the same Python process* to reload each adapter.
That validates model file roundtripping, but is not a process-restart test.

In this increment a **different, durable operating-system process** loads
the same pinned SmolLM2-135M-Instruct base and each of the eight already
trained adapters **from disk**. The original training process had terminated.
Every file in each checkpoint must match the original declared SHA-256 and
byte length before loading. A changed pinned base, tokenizer, disclosed
fixture, original training script or archived result is rejected. The
consumer checks every disclosed B/C task's ID, truth, prompt hash, prediction
and nine-decimal next-token probability against the original archive. It
neither retrains nor modifies any adapter. There is no network/GPU access.

| Observed readback | Value |
|---|---:|
| Independent durable host job | `1a1c8c5d9ea-135c4-229` |
| Authoritative result | succeeded, exit 0, complete durable stdout, 0 stderr bytes |
| Previously trained adapter arms reloaded | 8/8 (four seeds × two clocks) |
| Fresh-process actual model forwards | 96 (8 × [4 exposed B + 8 operator C]) |
| Largest difference from original archived p_yes | 0.0 at 9-decimal output precision |
| B accuracy, each clock, seeds 11/17/23/29 | 3/4, 2/4, 3/4, 2/4 |
| C accuracy, each clock, all seeds | 3/8 |
| Consumer total wall time | 6.792904 s |
| Consumer total process CPU time | 18.576632 s |
| Consumer process peak RSS | 1,197,936 KiB |
| Consumer physical read bytes | 147,116,032 |
| Consumer process character reads | 421,013,752 |

Authoritative input identities:
- Exact #5905 parent commit: `0ed4fce8bd07d361bf7eba40c40fe73d1f349c66`.
- Original actual producer job: `1a1c87b36af-135c4-9b` (terminal exit 0).
- Original public task/score archive SHA-256:
  `9512849b90964c35951bb8bb2226b3f2f6d3ec0da1e9a3b98467c8970afbe39c`.
- Original native training executable SHA-256:
  `4dded105ac0477c9747b13d98ee1b57d46dcc322d034121a55a9c63a12250e5e`.
- Fresh consumer executable SHA-256:
  `2fa4c8d22ef55ce54cb6e1e15672c7034ad9ef633d75a82daec7ed8739da267d`.
- New structured consumer result SHA-256:
  `728a491776fec240466a1cc6449da71a5fea29c3c37356ee5add4ccc749237c0`.

Command (requires local model and original adapter files; the GitHub CI does
not download model weights or rerun inference):

```sh
python fresh_process_readback_v2.py \
  --model PINNED_BASE \
  --fixture ORIGINAL_EXPOSED_EXPERIMENT_PLAN \
  --original-result real_cpu_clock_v2_RESULT.json \
  --adapter-root ORIGINAL_TRAINING_RUN_DIR \
  --out NEW_RESULT.json --threads 4
python3 -m unittest -v test_fresh_process_readback_v2.py
```

The pinned base and all eight adapters remain on authenticated heptaruntime
operator host `ai395`; structured results and source are in this PR. CPU
time, disk reads, wall and peak RSS are observed for the **consumer job**,
but omitted energy, data/label costs, failed owner effects and total lifecycle
cost cannot be inferred. CI tests compare the archived result against
identity/score invariants; **CI cannot independently attest the operator's
compute or that original Model owner ever used the adapter**.

## Non-transferable qualification boundaries

**This closes only the narrowly specified separate-process model-file
readback check.** It is not a different physical host, an independently
managed custody operator, an original Agentd owner cold restart, a Root
generation/anchor recovery, or an authorized next task. B and C were
previously disclosed/operator-written, not independently held future tasks.
There is no proof of scientific improvement, plasticity attribution, genuine
NoUpdate/Adopt, seven-lineage training, sparse/dense ACT/CTRL outcome,
MEM deletion, independent evaluator, Core × NDU 2×2, or production permission.
The original negative clock comparison and HOLD_NO_GO remain unchanged.

