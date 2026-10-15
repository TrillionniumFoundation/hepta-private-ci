# E2 physical crossmodal learning — original DINOv2 + original Granite97 (research only)

**Draft / SHADOW_ONLY / DENY_ALL. Never select or promote a Stem from this study.**

This child study extends the existing, separately owned:

- #2146 original pinned `facebook/dinov2-small` vision-source Encoder and train-only image/text ingress;
- #2149 independent original 2-image ZIP/identity audit;
- #1885 train-only frozen linear Bridge, rotated-target and unaligned controls, independently held geometry evaluator;
- #2136 five-arm natural multimodal *task* readout (not yet executed in full);
- existing V8 immutable `ibm-granite/granite-embedding-97m-multilingual-r2` material acquisition and V9 checked model handoff.

## What the new runnable workflow does

1. Author a fixed **synthetic** panel: 16 TRAIN colored shapes, 8 FUTURE colored shapes,
   each a genuine PNG file with new source bytes and independent case/group IDs.
   Seal `train_anchors` and separately hold future captions plus shape labels;
   no future labels go to the fitting job. The deterministic author is the same
   experiment designer, **not** an independently qualified human truth owner.
2. Acquire **the exact original DINOv2-small safetensors** at revision
   `150c8e7bb7cef2d30ec31b13a517af14840ee3f7`, original weight SHA-256
   `ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1`;
   refuse arbitrary loaded tensor differences or unexpected files.
3. Physically run **16 TRAIN + 8 FUTURE original vision forwards**, emitting
   source-bound 384-dimensional CLS/L2 features. Require train/source identity,
   exactly matching image file bytes, model revision, preprocessor and loader.
4. Physically acquire/forward the registered **Granite R2 97M** source at pinned
   revision `835ad14087e140460703cf0fae09f97d469d65c2` through existing
   V8/V9 + `execution.LocalEncoder` strict original-material checks. For TRAIN,
   fit source DINO features -> actual 384D Granite caption embeddings using
   inherited CPU f64 Ridge. Keep **rotated-target** and **unaligned** controls.
5. Pass FUTURE **source-only** original vision features through frozen three-arm
   Bridge. Seal `sealed_geometry_predictions.json` and class predictions before
   an independent job downloads its withheld future captions or labels.
6. Only the readout job obtains withheld future captions. It independently
   reacquires the same original Granite checkpoint, forwards its future target
   captions, and runs inherited independent geometry evaluation. A separate
   **pure-stdlib** scorer evaluates the sealed synthetic four-class
   predictions using the independently downloaded withheld labels, including
   rescued/harmed counts versus the unaligned identity control.
7. Preserve sanitized source/model/feature/fit/score receipts but **never raw
   pretrained model weights**. Every summary retains `DENY_ALL`.

The source-authoring, fit/predict and label-readout jobs have distinct input
artifact lists. This enforces **workflow-level file separation**, not proof of
cryptographic isolation from the Actions administrator or original source
provenance. Use pinned dependency/test layers. Queued or failed steps are not
model execution. The source and score gates reject train/future case/group/image
reuse, missing arms, forged image/question provenance, modified model/material
identity, missing actual-forward counts and target-bearing prediction records.

## Why this does not complete E2

**It tests physical two-model cross-modal interoperability on artificial
colored shapes, not natural image understanding.** The readout has **three**
Bridge/feature arms, not #2136's required five text/OCR/unaligned/learned/native
arms. Even a perfect toy class accuracy or aligned cosine does not prove a
semantic multi-hop decision, original grounded visual QA, an NDU learning
advantage, or improvement over a shared 421M baseline.

Natural image/video/audio with independently reviewed truth, the true OCR-only
and native EmbeddingGemma 2 arms, matched Reader/calibration/training and energy
budgets, three genuinely prospective nonoverlapping source families/windows,
negative transfer, and real 64/256/1024/4096 target-host Worker/FinalUse/restart
qualification remain blocked. A single synthetic future panel **is not** three
future windows. Do not report any model as selected or production qualified.

## Local fast tests, no external network

```sh
PYTHONPATH=experiments/shared_stem_cell python3 -m unittest discover \
  -s experiments/shared_stem_cell -p test_e2_crossmodal_physical.py -v
PYTHONPATH=experiments/shared_stem_cell python3 -O -m unittest discover \
  -s experiments/shared_stem_cell -p test_e2_crossmodal_physical.py -v
```

Source-only authoring (requires Pillow, but no model download):

```sh
python3 experiments/shared_stem_cell/e2_crossmodal_physical.py prepare --out /tmp/hepta-e2-synth
```

Physical model execution is controlled by the dedicated exact-source
`.github/workflows/hepta-e2-actual-two-encoder-bridge.yml` and **must run to
completion before any physical benefit claims**. CI requires original Owner
`blocking-ci` separately, and this research report never grants FinalUse.

## 2026-10-15 source-target isolation repair (child draft / scientific HOLD)

Actual original-model run [38677568171](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38677568171)
completed all four jobs at source `38635abede4e402b1afb6a74694a276b6a226cff`.
Original independent synthetic eight-case readout: fitted 8/8, TRAIN-target-rotated
0/8, unaligned identity 2/8; future Granite geometry mean cosine respectively
0.9430492161, 0.8844332554, 0.0146496909. This is an *exploratory* result
on synthetic drawings, not natural images, independent human semantic ground
truth, a five-arm outcome, or three genuine future windows.

**Discovered contamination:** The original authoring step included the hashes of
`future_caption_targets.jsonl` and `future_class_targets.jsonl` in the
`source-manifest.json` that was made available to the model/fit-predict job.
Hash-only exposure is *not* literal label access, but a small 4-class target
space permits dictionary attacks. It invalidates any claim that the original
producer was completely blind to future-target commitments. The synthetic
panel's generator also publicly defines its classes, so no truly independent
annotation can be claimed even after isolating SHA fields.

This follow-up requires exact disjoint manifests:

- `source-manifest.json` (producer accessible): exactly the four TRAIN/FUTURE
  image, TRAIN anchor and TRAIN class SHA pins. Zero future-target filenames or
  digests.
- `withheld/target-manifest.json` (independent evaluator only): exactly the
  future caption and future class target byte SHA pins, bound to the *byte SHA*
  of the source manifest. Both gates reject malformed/additional fields.
- A new physical workflow reruns full original DINO/Granite TRAIN and FUTURE
  encodings and the independent scorer at the amended **exact SHA**.
  Previously observed #2165 results remain available as explicitly
  pre-remediation historical exploratory data, not re-labeled as fresh results.

The independent target is still generated by deterministic synthetic code and
never a human OOD label source. File/digest binding is necessary, not sufficient:
future honest ground truth, natural-image ablations, matched cost, Reader
adequacy, non-regression, independent attestation, and 3 chronological
real-world future windows remain blocked. **DRAFT / SHADOW / DENY_ALL**.
