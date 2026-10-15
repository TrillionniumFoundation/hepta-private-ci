# E5 sparse Packed Head Bank: actual CPU SGD at 64–4096 Cells

**Shadow research / DENY_ALL.** This is an actual numerical PyTorch CPU study of *small Head update mechanics* with synthetic Q24 features and synthetic task labels. It does not execute Granite/mmBERT/Gemma, qualify a target Rust inference Worker, certify future NDU, or select/promote any Stem.

## Implementation and fair arms

The experiment `e5_sparse_packed_sgd.py` makes every logical Cell's full 9,744 FP32 parameters resident (384D feature, 64D local state, rank-8, 8 choices). It then selects a deterministic *noncontiguous* 10%-active set, shared by both arms, with three seeds (20261014/15/16), and executes three **real** `torch.optim.SGD` steps per active Cell using identical initial weights, feature/state bytes, label mapping, learning rate 0.01 and **sum of per-Cell cross-entropy**. Each arm runs in a different OS process.

- **Independent modules:** 64/256/1024/4096 separately instantiated Heads; only active modules take gradients; every dormant weight is SHA-scanned before and after. Audit hashes are **streamed**, not one huge byte concatenation.
- **Packed Bank:** the same full resident population held in six FP32 tensors; select only active weight rows into six trainable parameter tensors, run actual batched `torch.bmm` SGD, then scatter the updated rows back to their Cell indices. Do not allocate gradients or optimizer state for all dormant Head rows. Hash all dormant rows before and after; any mutation fails.
- Both modes use a **single physical synthetic Q24 input** with a zero-stride shared view. No gradient reaches the shared feature or private state. Smaller tests compare the actual updated weight tensors and logits elementwise within floating-point tolerance, rather than declaring success solely from aggregate training loss.
- `e5_sparse_sgd_review.py` independently checks a frozen 24-slot plan, *all* initial per-Cell and active-set digests, three losses per arm, update and dormant SHA continuity, real reported CPU/RSS/SGD timing, positive resident memory floor and false model/authority claims. One missing, duplicated, changed, or nonfinite arm fails rather than being interpreted as zero cost.

## Completed local physical results

One host, PyTorch **2.10.0+cpu**, Python **3.13.5**, one PyTorch CPU thread, three paired seeds; no GPU. All **24** successful OS-process receipts are source-bound in the sanitized local ZIP `hepta_e5_sparse_packed_sgd_24_receipts_20261014.zip` (SHA-256 `62b05c410c85da65f863c8535a4275581073959162ac4296d3eff4f960edfb16`). Individual source SHA digest manifest: `3773cbc98f44c9712c2bb886bbbabc04cc93ebb8dfe564e2b038c47f03fc0d10`; independent review SHA `dcc1e8bf293877b93f403e7c57bbb6ad84bde488a01867798f57673d50faeadb`.

| Logical Cells | Active | Median paired packed/independent SGD speedup (3 seeds) | Median measured process peak RSS saved |
| ---: | ---: | ---: | ---: |
| 64 | 8 | 1.78× | 1.1 MiB |
| 256 | 25 | 2.71× | 5.0 MiB |
| 1024 | 102 | 3.20× | 20.7 MiB |
| **4096** | **409** | **3.18×** | **84.3 MiB** |

Every complete pair matches initial parameter SHA, active Cell index SHA and three SGD losses within a strict numerical tolerance; all Heads really update, and dormant weights remain identical. **The 1024-Cell first seed is a negative speedup (0.77×), retained openly.** These are small, unblinded, non-random-order local microbenchmarks without inferential significance. Speedup is measured *SGD training-loop time*, **not full lifecycle, p99, or NDU utility**.

### Mandatory correction to initial 4096-Cell memory claim

The first-ever 4096-Cell independent-module experiment reported ~868 MiB RSS because its dormant-weight audit used an enormous `b''.join(...)` temporary allocation. That memory was an artifact of the audit, **not the learning architecture**. We switched to incremental SHA and reran every cohort. The valid paired 4096-Cell peak RSS advantage is ~84 MiB in the current three-seed panel, **not** 356.7 MiB or a 41% production memory saving. The original superseded 4096 observations remain in the local ZIP under `superseded/`, not mixed into the corrected statistics.

The first three-seed campaign also hit an external command timeout after partial completion; only missing slots were re-executed with per-process bounds. The local ZIP's `failure_history.json` discloses that incomplete attempt; no missing study slot is counted as a success and no bad completed speed ratio was dropped.

## Reproduce on exact source

```sh
python -m unittest discover -s experiments/shared_stem_cell \
  -p 'test_e5_sparse_*.py' -v

mkdir -p /approved/e5-cpu-raw
for n in 64 256 1024 4096; do
  active=$(( n / 10 )); if [ "$active" -lt 8 ]; then active=8; fi
  for seed in 20261014 20261015 20261016; do
    for mode in packed modules; do
      python experiments/shared_stem_cell/e5_sparse_packed_sgd.py \
        --cells "$n" --active "$active" --mode "$mode" --steps 3 --seed "$seed" \
        --output "/approved/e5-cpu-raw/$n-$mode-$seed.json"
    done
  done
done

python experiments/shared_stem_cell/e5_sparse_sgd_review.py \
  --receipts-root /approved/e5-cpu-raw --output /approved/e5-cpu-review.json
```

The dedicated read-only workflow `hepta-e5-sparse-sgd.yml` repeats all 24 true PyTorch CPU jobs in distinct processes, preserves even partial failed evidence using `if: always()`, and runs independent numeric audit. Its GitHub Actions receipt is **not complete until exact-HEAD CI really finishes**. Do not replace it with older local source results.

**Non-negotiable blockers:** signed and physical real Stem input, Reader adequacy, independent future1/2/3 NDU outcomes and OOD, life-cycle model load/feature cache/training/evaluation/checkpoint cost, target hardware queue/p99/RSS/power/GPU and true native Worker/fence/CAS/WAL/unclean recovery. All production/FinalUse/Evaluator-Selector-Executor authorities remain unchanged and all `blocking-ci` gates remain mandatory.

See [machine-readable summary](E5_SPARSE_PACKED_SGD_20261014.json) for per-seed paired ratios and source hashes.
