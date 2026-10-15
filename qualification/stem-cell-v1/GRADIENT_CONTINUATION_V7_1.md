# V7.1 — protect the actual *old* V6 binding skill before adding new natural-task ability

**Status:** DRAFT / SHADOW_ONLY / DENY_ALL; no production promotion. The predecessor is
[PR #2383](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2383)
(`research/bridge-gradient-conflict-v7-20261015`). V7's original source ordered
natural as **old**, binding as **new**. That was reversed: V6 first trains the
**binding-v4 paired-world** Bridge to 100% train accuracy, then does continual
training on the **new natural MultiRC** task. The original 
`bridge_campaign.py:continuation` and `binding_protocol.retention_gate` confirm
that the protected old capacity is the binding-world skill. V7's earlier
first-order gradient projection targeted the wrong objective; no V7 scientific
superiority claim may be inherited or retroactively repaired.

## Executable repair, not a theory claim

* `bridge_gradient_guard.py` explicitly defines `OLD_TASK` (binding) and
  `NEW_TASK` (natural). Every step computes one **old** CE+paired-margin loss
  against the actual original four-row binding cases, one **new** natural CE,
  two authentic backward passes, one proposed Adam update, and a third
  binding forward to observe the **post-Adam** old-task minibatch loss.
* Three registered comparable starting states: `joint` (no projection),
  `protect_old` (new gradient projected off old binding gradient), and
  `protect_old_guarded` (the same projection, but the candidate's **actual**
  old minibatch loss may not increase by more than `1e-6` per proposal).
  Guarded rejection atomically restores **parameter tensors and all Adam
  optimizer moments/step counters**. Do not count a rejected proposal as an
  accepted parameter update. All three arms have exactly 3 Reader forwards,
  2 backward calls, and 1 *attempted* optimizer step per logical update.
  Guarded snapshots/rollback and projection FLOPs differ; this is **not**
  strict equal-FLOPs or full-lifecycle cost parity.
* `bridge_gradient_campaign.py` uses the existing `checked_design`, pinned
  original V6 frozen warmup, real shared pretrained token feature cache,
  original train-only old/new source groups and the unchanged original V6
  500-step schedule. All 3 seeds (41/47/53) × all 3 arms must complete.
  Only original old **TRAIN** binding retention and labeled natural **internal
  tune** diagnostics are emitted. No official or future test labels are opened.
* `bridge_gradient_review.py` is pure Python standard library, run from a
  **separate process** after all 9 model files, source/report digests and
  create-only work products exist. It checks the original V6 source/parent
  ancestry; all 4,500 logged two-stream steps; complete old-binding/new-natural
  IDs and exposures; projection/rollback arithmetic; 13,500 Reader forwards,
  9,000 backward calls; model file/training receipt hash binding; and
  rejects rewritten producer bytes by pinning both V7.1 trainer SHA256s and
  the original V6 runtime inventory; it *independently recomputes* complete
  old binding TRAIN 128-example binary
  accuracy and 64 paired-world correctness from sealed probabilities.
  Importantly, this reviewer does **not** decode or numerically replay the
  trained `.pt` tensors and does **not** cryptographically authenticate the
  original publisher or the physical host. A passing review means receipt
  consistency, not learning or production acceptance.

## Local mechanism regression (no original pretrained weights available here)

```sh
cd qualification/stem-cell-v1
python -m unittest -v test_bridge_gradient_guard test_bridge_gradient_review
python -O -m unittest -v test_bridge_gradient_guard test_bridge_gradient_review
python -m compileall -q bridge_gradient_guard.py bridge_gradient_campaign.py \
  bridge_gradient_review.py test_bridge_gradient_guard.py test_bridge_gradient_review.py
```

Tests perform actual PyTorch forward/backward/Adam with a small, disclosed
artificial Reader; a separate stdlib reviewer checks synthetic fixture records
and tamper cases. **Do not interpret synthetic fixtures as pretrained accuracy.**

## Genuine pretrained original-data execution (requires existing external material)

```sh
python qualification/stem-cell-v1/bridge_gradient_campaign.py \
  --source /approved/multirc-source \
  --snapshot /approved/pinned-granite97 \
  --prepared /sealed/prepared-token-bank \
  --previous-main /sealed/original-v4 \
  --previous-native /sealed/original-v5-native \
  --previous-v5 /sealed/original-binding-v5 \
  --previous-v6 /sealed/original-bridge-v6 \
  --output /sealed/new-gradient-v7-1

# Separate standard-library reviewer process, independent from Torch trainer:
python -S qualification/stem-cell-v1/bridge_gradient_review.py \
  --previous-v6 /sealed/original-bridge-v6 \
  --output /sealed/new-gradient-v7-1 \
  --review /sealed/independent-gradient-v7-1-review.json
```

No original model weights, source cases, cached features or signed source/host
attestation were accessible in the current authoring container. Consequently
**no real 9-arm pretrained experiment or quality/cost winner is claimed**.
Preserve original V6 evidence; never overwrite prior artifacts or set CURRENT.

## Next scientific gates

First acquire all 9 original-run complete receipts and independently replay actual
saved trained tensor predictions from byte-verified V6 original train and future
source groups. Compare complete old/new task utility by original *source-group*
clusters, not candidate-row or seed-as-sample pseudoreplication. Match total
parameter, encoder cache, training data exposure and whole-lifecycle compute,
including poststep probes and guarded snapshot/rollback. Require stable retained
old tasks in all seeds AND useful new task capability versus a trained wide
unsplit Head, matched projection and no-change reference. Test real separate
calendar future windows; the 100%-fit TRAIN gate is not generalization. Keep
all candidate actions and NDU/FBSDE promotion at DENY_ALL until independent
science, target-host measurements and native owner authority complete.
