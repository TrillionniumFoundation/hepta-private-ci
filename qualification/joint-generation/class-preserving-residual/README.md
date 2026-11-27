# Frozen text marginal: a negative independent RGB experiment

**Not a resumed round04 experiment.** The 2026-10-30 environment lacked the
private round04 models, data, and original benchmark lock. This newly authorized
experiment instead uses the complete, already published finite RGB generator and
`JointModel` at commit `2fa44443f6e293c31ee7e6b3bc3f7d49770398a3`.
The old six quality failures and round04 budget failure are unchanged.

## Mechanism and matched control

Earlier served-risk decomposition found that class-mass losses offset image gains.
A concrete attempted remedy is to prevent the text marginal from drifting while
adapting the image branch. `SplitPolicy` returns:

- **joint:** both marginals from a trainable copy; its update is exactly the
  original additive or NDU objective pullback.
- **protected:** text probabilities from the immutable pretrained model and image
  probabilities from a separately trained copy. The image gradient uses the
  original joint utility at that fixed text marginal; its text pullback is zero.

This preserves the entire text probability array exactly, not just argmax or an
average metric. It is an actual two-model serving law, not algebraic score mixing.
The output law remains independent text/image categoricals over 12 contents;
the original 144-outcome entropic utility, rho=1.5, and actual decoded RGB observer
are unchanged. The original renderer is used only for training/observing targets,
never to generate inference outputs. The decoder is frozen and verified identical:
this intervention changes **image-content probabilities**, not pixel-decoder quality.
The directory's residual-candidate name does not imply a learned pixel residual.

Both arms execute the same two forward calls and the original gradient machinery.
The joint arm's spare frozen-model forward is deliberate matched-work overhead.
An optimized original one-model baseline is cheaper: this is not a latency or
compute-efficiency improvement claim. Optimizer state is freshly initialized for
all adaptation arms, just as upstream `clone()` specifies; no old checkpoint
optimizer state is silently reused.

## Frozen experiment

- Seeds 11 and 23; joint/protected × additive/NDU = **8 cells**.
- Original 300 decoder steps and 500 supervised pretraining steps per seed.
- 300 adaptation updates, batch 64, mixed full/low inputs, hidden 32, anchor .2.
- Fixed learning rate .003: no search or validation selection.
- Six variants per source; 260 training groups and 86 validation groups.
- Every final model saved and hashed **before validation generation**.
- Both full and low inputs reported; their equal-weight mean is primary.
- No TEST generation or evaluation. Existing benchmark validation is reused and
  results are exploratory, not new independent held-out confirmation.
- Both main contrasts require rho gain >= .005 and no loss of text mass,
  greedy text accuracy, joint success, or image MSE, in **both seeds**.

`FREEZE.json` binds the executed code and plan. Five literal tests check zero-step
identity, exact preserved marginals, untouched baseline, original-control update
identity, finite-difference image gradients, and invalid input rejection.

## Actual result: rejected

| Contrast | Seed | Delta rho | Delta text mass | Delta image MSE |
|---|---:|---:|---:|---:|
| protected N − joint N | 11 | −0.12364197 | −0.08175182 | +0.00013512 |
| protected N − joint N | 23 | −0.13440933 | −0.08973227 | +0.00022730 |
| protected N − protected A | 11 | +0.00476660 | 0 (exact) | −0.00034920 |
| protected N − protected A | 23 | +0.00421589 | 0 (exact) | −0.00033786 |

The protected model preserves the **pretraining** text marginal, but the joint
baseline learns a substantially better text marginal during its extra updates.
Freezing early blocks useful learning. It also fails to improve image MSE versus
the joint control. NDU improves the protected arm over additive on the recorded
metrics, but neither seed meets the prespecified .005 threshold. **No quality
success is claimed.** All six contrasts and every arm remain in `RESULT.json`.

The justified next mechanism is to train a separate supervised text branch rather
than freezing it, while training the image branch with additive/NDU utility. That
is a new prospective experiment, not a rescue or reinterpretation of this result.

## Actual cost and boundary

Complete waited driver plus its reaped children: **3.211034 CPU seconds**, **3.213146
wall seconds**. Tests: .152582 CPU; scientific worker: 3.028394 CPU; complete driver
own CPU: .030058. Five tests passed; all eight 300-update cells finished.

The independent campaign ceiling was 400 CPU / 600 wall seconds, and each method
had the same 60 CPU-second cap. Full conservative per-method charges were
.852195–.888228 seconds. These include its own entire pretrained base plus **all**
shared preparation, qualification tests, imports, checkpoint/report work, and
waited process tails—not merely amortized shares. Physical campaign shares are
also preserved separately. Equal caps do **not** mean equal actual spend.

`FINAL_COST.json` closes the original child-only supervisor-tail uncertainty by
waiting the whole driver. The outer settlement report writer's own cost and
historical source/review/recovery/publication work remain separate unmeasured
costs, **not zero**. Thus the recorded prospective instrumented execution passes
its caps; no assertion covers all historical R&D or every external reporting cost.
The quality gate fails regardless.

The new lock is explicitly synthetic-only. It never replaces or bypasses the
missing original round04 lock. Models and generated request data stay local and
are not part of this publication. No merge, deployment or hosted-CI claim.

## Reproduction

From this repository, with NumPy installed:

```sh
python3 -I -B qualification/joint-generation/class-preserving-residual/test_mechanism.py
python3 -I -B qualification/joint-generation/class-preserving-residual/settle_once.py /absolute/new/output
```

The second command creates the independent synthetic lock at the documented
workspace path, refuses existing output directories, and stops if the lock is
held. Coordinate this lock before any related numerical experiment.
