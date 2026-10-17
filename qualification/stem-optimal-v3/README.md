# Hard-charge Stem selection V3: preregistered original research extension

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO / NO MAIN MERGE / NO PRODUCTION MODEL / NO CELL SPLIT.**

## Immutable parent and hypothesis

Parent: PR #2567, commit `ef719ef84967789365790bf39b3055653ff73430`.
Historical original V1/V2 files and Action ZIP custody are unchanged.

The physically executed original BANKING77 4-class cohort reported **32/32
accuracy for both Granite learned Heads AND their cheap supervised centroids**.
That is a ceiling and supplies no incremental correctness evidence for learned
Heads. Rather than re-score or cherry-pick its 32 official heldout observations,
V3 pre-registers a new, lexically overlapping four-intent **same-publisher**
canary before executing any V3 original model or opening V3 heldout labels:

1. `card_payment_fee_charged`
2. `cash_withdrawal_charge`
3. `exchange_charge`
4. `transfer_fee_charged`

Exactly 16 publisher TRAIN and 8 publisher TEST cases per intent; complete
source-text SHA sorting is separately salted for V3. Full publisher Git SHA and
TRAIN/TEST CSV byte SHAs stay immutable. No purported timestamps, no temporal
future windows, no claims of source-disjoint transfer or human adjudication.
V3 has its own source/receipt/reviewer schemas; **never reinterpret the original
V1 cohort as a V3 cohort or modify V1/V2 evidence**.

## Physical workflow

`.github/workflows/hepta-stem-optimal-hard-charge-v3.yml`:

- First-run source-only negative tests; publisher original source owner emits
  training labels and heldout text **without heldout labels**.
- Three pinned original pretrained CPU Encoder jobs, sharing V1's exact
  47M/97M/mmBERT140 weight byte checks, native tokenizer / forced masked-mean
  384D output, 128-token limit, and matched four 6,914-scalar gated Heads.
  Same 100 Adam steps, frozen initialization and supervised train centroids.
- A separate runner re-downloads the original publisher TRAIN/TEST bytes only
  **after** SHA-sealed prelabel predictions exist, independently reconstructs
  cohort IDs and late heldout labels, rejects identity/Head/cost substitutions,
  and publishes paired accuracy, multiclass Brier and nominal McNemar evidence.
- Independent public runner counts are not matched target-host lifecycle
  measurements. Do not infer lower power, GPU costs, comparable model FLOPs,
  a winner, prospective NDU gain or permission to route/activate any Cell.

Physical original jobs run on a push to the exact research branch only.
Pull requests run source-only tests; passing them is **not physical evidence**.

## Reproduce source-only checks

```bash
python -m unittest discover -s qualification/stem-optimal-v3 -p 'test_stem_hard_charge_v3.py' -v
python -O -m unittest discover -s qualification/stem-optimal-v3 -p 'test_stem_hard_charge_v3.py' -v
python -m py_compile qualification/stem-optimal-v3/*py
```

Production gates remain closed pending source-independent and prospective
windows, frozen deployed 421M/no-change matched full lifecycle, calibration,
negative transfer, actual NDU utility, signed worker/FinalUse authority,
64/256/1,024/4,096 Cell physical host measurements and recovery.
