# Grounded generation with bounded Hepta control

This experiment evaluates dynamic allocation among four small decoder Cells on a frozen Florence-2 base. The task is to locate every instance of a requested COCO category, count the predicted boxes, identify whether the largest box is left or right of the image center, and return an explanation with an annotated image. The comparison concerns this structured-grounding prototype.

[protocol.json](protocol.json) fixes the cohort, methods, budget, selection criterion, calibration role, scoring and statistical interpretation. Revision 2 was refrozen before development selection and final testing to share one same-prompt Encoder across best-of-2 candidates and provide pinned acquisition entrypoints. Preserve its SHA256 with the run receipt. Changes motivated by final-test outcomes belong to a new protocol and an independent evaluation cohort.

## What the model generates

`backend.py` executes the pinned `florence-community/Florence-2-base` model with its native `<CAPTION_TO_PHRASE_GROUNDING>` task. The adapter translates the fixed public task into that task token followed by `target_category`; it does not evaluate arbitrary instruction following. The model decodes the grounding sequence and bounding boxes from image-conditioned tokens.

The explanation is a deterministic rendering of the category and predicted boxes. `generation.py` draws those same predictions on the original image and saves a content-addressed PNG. Consequently, this run evaluates grounding and control of a real generative decoder. It does not separately measure learned free-text explanation, pixel generation, or independent semantic agreement between two generative modalities. Label and text-consistency scores are structural checks under this adapter, rather than independent evidence of category recognition or language generation.

The frozen base uses revision `00921df66db728a9ceb750f5eca43e5c203a2051` and weight SHA256 `62f3e696da74f8869a68ddb529a9b3e14eb25b21c592cb3dea6179bf944df6a0`. Loading verifies the weight file. The Cell-training receipt also compares model tensor hashes before and after training.

## Data and truth separation

`cohort.py` selects one task per original image from the official COCO `instances_val2017.json`. Selection uses annotations and a fixed hash order, without model output. Each selected category has 1–3 instances, all non-crowd with valid boxes; its largest bounding-box area covers at least 4% of the image. Categories with tied largest boxes or an exactly centered largest box are excluded. License IDs 4 and 5 match the prior research roster.

| Split | Original-image groups | Permitted role |
| --- | ---: | --- |
| train | 128 | Teacher-forced Cell fitting; random exploration; policy and verifier fitting |
| dev | 32 | Choose NDU risk weight from the fixed grid |
| calibration | 32 | Adjust verifier severe-error probability only |
| test | 64 | Fixed final comparison and descriptive statistics |

The historical 384-image cohort is excluded. File SHA256, decoded RGB SHA256 and horizontal 64-bit dHash distance at most 4 screen historical and newly selected images for duplicates. The split unit is the original image. COCO does not establish that people or other real-world entities never recur across images, and overlap with the base model's pretraining data is not excluded.

Each `<split>.observations.jsonl` row has exactly five public fields: `task_id`, `image_path`, `image_sha256`, `prompt`, and `target_category`. The actor-facing loader does not open references. Each separate `<split>.references.jsonl` contains `task_id`, `source_id`, `image_size`, normalized XYXY `boxes`, `label`, `count`, and `largest_side`.

`prepare.py` uses train references for teacher forcing. During exploration, the parent scores completed train episodes and attaches terminal outcomes to the offline training trajectories. Generation workers and inference callbacks receive observations, never reference rows. Source-integrity validation may read reference files from every split; final-test outcomes do not enter fitting, development selection, or calibration. Small smoke cohorts and synthetic test fixtures do not substitute for the fixed evaluation roster.

## Cells, decisions and the discrete BSDE scope

The four Cells are rank-16 sparse residual adapters over a common decoder vocabulary:

| Cell | Training role |
| --- | --- |
| semantic | Lexical tokens in the train-derived vocabulary |
| horizontal | Horizontal location tokens |
| vertical | Vertical location tokens |
| completion | Sequence-boundary token corrections |

They share one frozen encoder/decoder backbone. They are not four modality generators. Residual logits are bounded by `3*tanh(raw/3)`, and teacher-forced training preserves the frozen softmax's outside-vocabulary mass in the normalizer.

The controller chooses among six portfolios: zero residual, uniform four-Cell weights, or one of four one-hot allocations. A decision may change every four decoded tokens. The backend supports eight control checkpoints and at most 48 new tokens. Eight is a capacity: a sequence reaching EOS after two or three decisions has only two or three actual checkpoints. The last selected weights remain active after the final allowed decision. Receipts retain token-level interventions and measured checkpoint counts.

Train exploration attempts two seeded trajectories per image, with each portfolio chosen with probability 1/6 at a checkpoint and greedy token decoding thereafter. Policies consume 24 observed uncertainty, prefix-geometry and Cell-disagreement features, with hidden width 32. All four policy networks begin with the same weights and fit only train trajectories. Training metadata records actual usable trajectories and action counts.

For NDU, quality and loss each have a value head `Y` and six action coefficients `Z`. For an observed action and its recorded behavior distribution:

```text
delta_M = one_hot(action) - behavior_probabilities
residual = Y(next_state) - Y(state) - Z(state) dot delta_M
```

The last next-value is the actual train terminal quality or loss. The fit combines this path residual, terminal boundary, a Monte Carlo value anchor, centered-Z regularization and an actor improvement objective. Inference samples a conservatively mixed action distribution whose KL divergence from the pooled exploration distribution is at most 0.25. Explicit per-episode/checkpoint seeds make this sampling independent of other random draws.

This is a discrete action-basis BSDE prototype performing finite offline policy improvement. The 24 features are not asserted to be a complete state, finite exploration does not establish coverage of unseen states, and residual fitting is not an optimality proof. No continuous FBSDE or Merton problem is claimed solved.

The optional 4×4 matrix is the current token-probability-weighted covariance of Cell logit residuals, with zero correction outside their vocabulary. Its portfolio penalty is `risk_weight * 0.05 * w.T @ C @ w`. It is a local disagreement proxy, not a covariance estimate of terminal semantic losses. The policy risk score uses predicted mean loss, fixed-threshold hinge loss and probability of loss above 0.5; that score is not the evaluator's CVaR or its severe-error indicator.

## Comparison arms

| Baseline | Executed mechanism |
| --- | --- |
| `base` | Frozen base with greedy token generation and no Cell controller |
| `static_cells` | Uniform Cell weights with prefix geometry constraints |
| `learned_router` | Terminal-quality-weighted supervised action cross-entropy |
| `best_of_n` | One shared same-prompt Encoder execution, then at most two independent decoder candidates under one total cap; first greedy, second sampled at temperature 0.7; train-fitted quality verifier selects |
| `mean_only` | Quality-only offline actor–critic; risk weight is zero |
| `risk_actor_critic` | TD/return-anchored critic and fixed-threshold risk heads; no BSDE path residual |
| `ndu` | Discrete BSDE critics, sampled portfolio policy and local-matrix penalty |

| Ablation | Exact intervention |
| --- | --- |
| `ablate_covariance` | Disable the 4×4 portfolio penalty. Diagonal disagreement features remain in the 24-dimensional state. |
| `ablate_fixed_weights` | Uniform weights throughout; behavior duplicates `static_cells` under the same constraints. |
| `ablate_crossmodal` | Remove prefix syntax and coordinate-order constraints. This is a geometry-constraint ablation; it does not test an independently learned cross-modal semantic constraint. |
| `ablate_missing_modality` | Replace the image with a same-size black image; retain the requested category and execute the encoder. |
| `ablate_shuffled_pair` | Substitute the next image in the same split while retaining the original category; score and render on the original source. |

## Fixed scoring, selection and calibration

`evaluate.py` matches boxes by maximum-cardinality one-to-one matching at IoU at least 0.5. A reference box can count once. Box F1 is `2*matches/(predicted_count + reference_count)`.

For a valid completed output:

```text
quality = 0.5*box_F1 + 0.2*count_correct + 0.1*largest_side_correct
        + 0.1*label_correct + 0.1*text_consistent
loss = 1 - quality
```

Validity requires completed generation, valid normalized boxes, a decodable PNG with matching digest and original dimensions, a complete measured cost receipt, and actual duration within the cap. Invalid, incomplete or over-budget outputs receive quality zero and remain in the denominator. Artifact validation checks bytes and dimensions; it does not independently score whether the drawn pixels exactly trace the box plan.

An episode is severe if it is invalid/incomplete/over-budget, if count, side, label or text consistency is wrong, or if box F1 is below 0.5. Report mean quality, severe-error rate, coverage, mean measured wall time and `CVaR_0.9(loss)`. CVaR uses fractional boundary mass: on 64 test images, sum the six largest losses and 0.4 of the seventh, then divide by 6.4.

Development selection evaluates NDU risk weights `[0.0, 0.5, 1.0]` at seed 23 and maximizes `mean_quality - 0.5*CVaR_0.9`; ties choose the smaller weight. Base and static Cells provide development context. Development selection does not update network weights.

Calibration runs the 12 arms on the separate 32-image split. It fits only a positive Platt scale and offset for the train-fitted verifier's severe-error probability. It changes neither the quality ranking used by best-of-N nor policy weights. It does not calibrate the NDU critic heads. These 384 planned outputs remain 32 source groups, not 384 independent images. Final evaluation reports verifier Brier scores separately from generation quality and tail loss.

Final testing uses all 12 arms, the same 64 images, and seed 23: 768 planned episodes. Source-paired bootstrap intervals use 2,000 resamples and seed 20261022, comparing NDU with the six other baselines. The intervals are descriptive 95% percentile intervals, without multiplicity adjustment. One evaluation seed and this finite cohort do not independently establish confirmatory improvement. `engineering_pass` verifies complete interpretable receipts; `experiment_pass` is not automatically promoted by observing a nondominated point.

## Costs and the frontier

Every arm has a 10-second episode cap. Receipts contain exclusive durations for encoder, backbone, Cells, controller, critic, verifier, rendering and communication. Each episode executes and charges its Encoder once. The two same-prompt best-of-N candidates reuse that encoded state and independently execute their decoders; every decoder, sampling and verification cost remains charged. Encoded inputs are not shared across different arms or tasks. Failed-attempt elapsed work is retained; unavailable internal token/call counts are marked explicitly. A forward call cannot be preempted precisely at the wall-time boundary, so actual overruns are retained and invalidate output quality rather than being clipped to ten seconds.

The measured scope is a warm, resident worker episode. Model loading and initial tensor hashing, worker startup, offline training, parent terminal scoring and journal persistence are outside that episode cap and must be reported separately for a full-system cost claim. Cells communicate through local callbacks; this prototype supplies no distributed communication benchmark. Method order rotates across images to reduce a fixed warm-up/order advantage.

A common cap does not imply equal actual cost. The reported empirical frontier consists of nondominated points in quality, CVaR, measured wall time and coverage at that cap. It is descriptive of these measured policies; an equal-actual-cost or matched-coverage improvement requires an additional comparison designed for those conditions.

## Reproduce

Run commands from the repository root, with outputs outside the checkout. [requirements.txt](requirements.txt) pins the observed CPU dependencies: PyTorch 2.10.0+cpu, torchvision 0.25.0+cpu, Transformers 5.20.2, tokenizers 0.23.3, NumPy 2.2.6, Pillow 11.3.0, safetensors 0.8.0 and huggingface-hub 2.2.0. The observed Python version is 3.12.14. These are environment pins, not a claim of bitwise portability across CPU hardware or thread scheduling.

```bash
export HEPTA_CODE="$PWD/qa/ndu-grounded-generation"
python3.12 -m venv /absolute/path/hepta-ndu-venv
export HEPTA_PY=/absolute/path/hepta-ndu-venv/bin/python
"$HEPTA_PY" -m pip install -r "$HEPTA_CODE/requirements.txt"
export HEPTA_RUN=/absolute/path/hepta-ndu-run
export HEPTA_MODEL="$HEPTA_RUN/model"
export HEPTA_COHORT="$HEPTA_RUN/cohort"
export HEPTA_WORK="$HEPTA_RUN/experiment"
mkdir -p "$HEPTA_RUN" "$HEPTA_WORK"
"$HEPTA_PY" "$HEPTA_CODE/acquisition.py" --model-dir "$HEPTA_MODEL" --annotations-output "$HEPTA_RUN/source_instances_val2017.json"
```

[acquisition.py](acquisition.py) downloads the 11 pinned Florence files directly without a duplicate Hub cache, verifies each size and SHA256, and obtains `annotations/instances_val2017.json` through exact ranges of the official COCO archive. It checks the local ZIP header, member name, decompressed size, CRC32 and fixed member SHA256. Its receipt verifies that member, not the complete archive. Existing matching files are reused and mismatching files are rejected. Keep both acquisition receipts.

[historical_exclusions.json](historical_exclusions.json) is a cohort-compatible wrapper for the same historical 384 image IDs and fingerprints. It makes reproduction independent of an earlier `/tmp` cohort. Its bytes and hash differ from the old manifest because its wrapper and path differ; the excluded original-image roster is unchanged. Pass it explicitly:

```bash
"$HEPTA_PY" "$HEPTA_CODE/cohort.py" --annotations "$HEPTA_RUN/source_instances_val2017.json" --output-dir "$HEPTA_COHORT" --image-cache "$HEPTA_RUN/images" --exclude-manifest "$HEPTA_CODE/historical_exclusions.json" --sizes 128,32,32,64 --download-images
"$HEPTA_PY" -m unittest discover -s "$HEPTA_CODE" -p 'test_*.py'
sha256sum "$HEPTA_CODE/protocol.json" > "$HEPTA_WORK/protocol.sha256"
```

Absolute paths and acquisition-manifest serialization affect local manifest hashes. Preserve the exact manifest of each run; compare original-source rosters and pinned source bytes when reproducing on another filesystem. The cohort builder refuses to overwrite an existing frozen manifest.

### Six execution stages

1. **Prepare train features and fit Cells.** Only train references enter teacher forcing.

   ```bash
   "$HEPTA_PY" "$HEPTA_CODE/prepare.py" --model "$HEPTA_MODEL" --cohort "$HEPTA_COHORT" --output "$HEPTA_WORK/training" --epochs 15
   ```

2. **Collect train exploration and fit policies/verifier.** This attempts 128 images × seeds 23 and 41. Inspect the retained counts and failures rather than assuming all attempted trajectories are usable.

   ```bash
   "$HEPTA_PY" "$HEPTA_CODE/experiment.py" collect --model "$HEPTA_MODEL" --cohort "$HEPTA_COHORT" --work "$HEPTA_WORK" --budget 10 --workers 2
   ```

3. **Select the fixed risk-weight candidate on dev.** This writes `selection.json`.

   ```bash
   "$HEPTA_PY" "$HEPTA_CODE/experiment.py" select --model "$HEPTA_MODEL" --cohort "$HEPTA_COHORT" --work "$HEPTA_WORK" --budget 10 --workers 2
   ```

4. **Calibrate verifier probability on calibration.** This writes a separate calibrated verifier and leaves the train-fitted ranking/policy unchanged.

   ```bash
   "$HEPTA_PY" "$HEPTA_CODE/experiment.py" calibrate --model "$HEPTA_MODEL" --cohort "$HEPTA_COHORT" --work "$HEPTA_WORK" --budget 10 --workers 2
   ```

5. **Execute the frozen final test.** Check the protocol digest before opening final-test outcomes. This phase also writes `report.json` from the retained episodes.

   ```bash
   sha256sum -c "$HEPTA_WORK/protocol.sha256"
   "$HEPTA_PY" "$HEPTA_CODE/experiment.py" test --model "$HEPTA_MODEL" --cohort "$HEPTA_COHORT" --work "$HEPTA_WORK" --budget 10 --workers 2
   ```

6. **Independently rescore retained outputs.** The evaluator reads episode receipts, reference files and PNG bytes; it does not call the actor.

   ```bash
   "$HEPTA_PY" "$HEPTA_CODE/evaluate.py" --references "$HEPTA_COHORT/test.references.jsonl" --episodes "$HEPTA_WORK/test.episodes.jsonl" --artifact-root "$HEPTA_WORK/artifacts" --output "$HEPTA_WORK/independent-evaluation.json" --alpha 0.9 --bootstrap-samples 2000
   ```

Phase journals are append-only and resumable under unchanged recorded identities. Retain the protocol digest, cohort/source manifests, model revision and weight hash, Cell/policy/verifier checkpoints and training receipts, selection/calibration records, phase run manifests, complete episode journals and all referenced PNGs. A scientific rerun uses a new work directory; it must not silently combine results from different checkpoint or implementation identities.

## Further scientific gates

The next capability claims require their own evidence: 8–16 actual decisions on tasks long enough to exercise them; independently generated language and pixels with cross-modal semantic assessment; terminal-output loss covariance estimated from independent outcomes; comparison at matched actual cost and coverage; independent confirmatory cohorts and additional decoding seeds; and a complete state/noise model for continuous FBSDE or Merton control theory. Passing source, replay or artifact checks does not close these separate questions.

## Post-hoc PNG outline audit (supplemental, not part of the frozen pilot)

The original experiment intentionally scored PNG byte integrity and dimensions, not
whether each drawn rectangle matched its own predicted coordinates. The
[separate overlay auditor](overlay_audit.py) now checks the four visible red
perimeters of every predicted box in the archived test PNGs, using the
content-addressed artifact digest and reference frame size independently from
the generating actor. A small tolerance allows palette quantization. This
post-hoc screen uses a 90% perimeter coverage threshold and has synthetic
negative controls for shifted boxes, digest tampering, size mismatches,
malformed digests, invalid boxes and duplicate rows. It does **not** inspect
the original JPEG, prove that the boxes locate real objects, or establish
independently generated image pixels or language.

The supplemental receipt is recorded at
[overlay-geometry-audit.json](../ndu-grounded-evidence/2026-10-22/overlay-geometry-audit.json).
It checks 768 test episodes and 820 predicted rectangles: no mismatched
perimeters, minimum eligible-rectangle coverage 0.952380952. It also accounts
for ten outputs with no predicted boxes. The original 768 pilot scores,
experiment selection, calibration, and protocol remain untouched.

To independently repeat this supplemental check after unpacking the pinned
evidence archive, with the repository checkout still available:

```bash
python qa/ndu-grounded-generation/overlay_audit.py \
  --episodes /absolute/path/to/bundle/raw/test.episodes.jsonl \
  --artifact-root /absolute/path/to/bundle/artifacts \
  --references /absolute/path/to/bundle/cohort/test.references.jsonl \
  --output /absolute/path/outside/bundle/overlay-geometry-audit.json
python -m unittest discover \
  -s qa/ndu-grounded-generation -p 'test_overlay_audit.py'
```

This later audit is not inside the immutable 831-file original ZIP manifest
and is not used to revise the experiment outcome. Test thresholds and this
screen were introduced after original test results became available. The
[model-free evidence replayer](../ndu-grounded-evidence/2026-10-22/portable-replay.json)
continues to validate the original pilot independently.
