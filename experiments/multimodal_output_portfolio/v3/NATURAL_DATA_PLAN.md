# Natural-data blocker: assets, implementation contract and closure gates

Date: 2026-10-23. Status: **plan; natural generation and foundation-model validation remain uncompleted**.

This document preserves the registered v3 experiment. Natural-data work must have a new experiment directory, a new data manifest and a new preregistration. No proposed threshold below changes a v3 success criterion. Data-I/O, pretrained image/video-frame codec checks, text interfaces and an audio codec roundtrip have now been executed separately on one source fixture; the remaining joint-model steps are proposals, not measured results.

## 1. What exists in this checkout

A read-only inventory used `rg --files`, including ignored files while excluding `.git`, Rust build output and dependency directories. No natural paired audio/video/text corpus and no natural-data pretrained `.pt`, `.pth`, `.safetensors` or comparable checkpoint were found. The repository contains source, receipts, plots, synthetic experiments and unrelated icon/test images. Those images are not an audiovisual dataset.

The known v2 checkpoints outside git are the synthetic `seed-{17,29,43}/supervised-model.pt` files referenced in `v3/protocol.json`. Their eight-concept model has 660,488 parameters; `model.py`, `metrics.py` and `feedback_control.py` rely on eight-dimensional portfolios, eight canonical targets or enumerated class conditions. These weights cannot become a natural multimodal model by resizing input tensors or relabeling their outputs. The v3 refiner additionally assumes a known source-conditioned anchor with externally imposed, finite-support disturbances. Its measured mechanism does not establish natural generation quality.

After this inventory, the separate authorized codec check acquired official MIT TAESD assets in `/tmp/hepta-taesd-assets`, outside git. Their pinned code/weight commit and hashes are in `../natural_io/evidence/codec-001.json`. These are pretrained image-codec weights, not a natural conditional multimodal generator.

The subsequent text check also acquired pinned Apache-2.0 T5-small assets in `/tmp/hepta-t5-small-assets` and ran an isolated `/tmp/hepta-natural-text-env` with Transformers `4.57.1` and safetensors. Its execution and independent review receipts are `../natural_io/evidence/text-interface-001.json` and `../natural_io/evidence/review-text-interface-001.json`. These later additions do not change the initial repository/runtime inventory or the frozen v3 experiment.

The audio check subsequently acquired the author's original MIT DAC 16 kHz release `0.0.5` in `/tmp/hepta-audio-codec-001` and used the isolated `/tmp/hepta-audio-codec-env-001` runtime. Final execution receipt `../natural_io/evidence/audio-codec-003.json` and `../natural_io/evidence/audio-codec-independent-verification.json` record safe strict loading, real integer-code reconstruction and independent artifact/metric verification. These external pretrained components are now available locally; they are not connected into a shared natural generator.

Runtime inventory in `/tmp/hepta-output-portfolio-env/bin/python`: PyTorch `2.5.1+cpu`, CUDA unavailable, 9 visible logical CPUs; NumPy and Pillow installed; FFmpeg and FFprobe present. `transformers`, `diffusers`, `datasets`, `torchaudio`, `torchvision`, `av` and `safetensors` were absent. No GPU is implied by the native Rust bridge or by the existing checkpoints.

Useful existing code, with its limit:

| Existing asset | Reusable part | Required change for natural work |
|---|---|---|
| `v3/feedback_model.py` | Immutable stream, feedback-before-action, complete emission, explicit work receipt | Replace the eight-class source, fixed 64-vector state and known-clean-anchor contraction; retain lifecycle checks |
| `v3/native_bridge.py` | Executed native STOP/REFINE, budget and output-seal protocol | Bind new model/context/state digests and real costs; retain that hashes are caller supplied, not remote attestation |
| `v3/feedback_control.py` | Small exact-tree oracle for controller tests | A continuous natural generator cannot enumerate every future latent; use a calibrated learned value model or bounded sampled planning, with its cost reported |
| `v3/risk.py` | Entropic/robust utility arithmetic | Recalibrate terminal metric units and uncertainty laws using natural training/development data |
| `codex-rs/hepta-learning-ledger/src/dataset_receipt_v3.rs` | Source-record, inclusion-policy, correction and revocation digests | Bind an actual media/annotation manifest; an empty digest or invented dataset receipt is not evidence |
| `codex-rs/hepta-bellman-operator/src/dataset_bound.rs` | Verification that training rows belong to a frozen source set | Natural adapters are not yet wired to this interface; a Python JSON manifest alone does not demonstrate native ledger integration |

## 2. A real natural-input fixture has been ingested

The independently authorized smoke is in `../natural_io/`, outside registered v3 source. Its [README](../natural_io/README.md) and [receipt](../natural_io/evidence/ingestion-001.json) record one Commons source by **Fiver, der Hellseher**, published as own work under CC BY-SA 4.0. The exact media URL, pinned page revision, source license, author and integrity hashes are preserved. [S1–S2]

Actual observations: 12,123,649 bytes; 10.483 seconds; VP8 3840×2160 at 25 fps with 262 decoded video frames; Vorbis 44.1 kHz stereo. Extracted tensors are audio `[1,167602]` at 16 kHz, image `[3,144,256]`, video `[4,3,72,128]` and 55 bytes of existing human German description. They are finite and nonempty; consecutive video frames differ. Original SHA-256: `bc957c8a0382d9a4d2d54acbfc61c61e5fd57bcef909364bad3f41a5957c91ef`.

This is **natural video + its recorded sound + a sampled natural frame + human descriptive text**. The image is derived from an existing real temporal recording, not an independently photographed image. The video is not generated from a still. The description is neither synthesized speech nor an ASR transcript. One example does not support a train/test split, quality statistics or generalization. In this ingestion check no model was loaded and no neural output was generated.

Closed narrowly: real media decoding and typed input-tensor feasibility. Still open: cross-modal semantic alignment, learned conditional four-output generation, useful feedback, global NDU training, independent natural-data generalization and foundation-model scale.

The subsequent [TAESD codec receipt](../natural_io/evidence/codec-001.json) additionally records real pretrained image and four-frame codec roundtrips at commit `fdbae2df989db95761f482efb8977e1182fb68d2`. Frozen weights were loaded with `weights_only=True`; image PSNR is 18.7792 dB and aggregate video-frame PSNR 19.3917 dB after RGB clipping. Five actual encoder/decoder roundtrips took 0.93395 s forward wall time; the complete measured main function took 1.65787 s wall. Fine-detail loss is visible. This closes only the image/video-frame part of codec integration, not temporal modeling, audio/text model interfaces, semantic quality or conditional generation. Full provenance, raw/clipped errors, CPU times, convolution MAC counts and reconstruction artifacts are in the [codec README](../natural_io/README.md).

The separate [T5 execution receipt](../natural_io/evidence/text-interface-001.json) now records a text encoder `[1,25,512]`, first-token decoder logits `[1,1,32128]`, and actual bounded autoregressive generation from the human description. The saved 26-token sequence includes one start token and 25 new tokens including EOS; 32 was the cap. Generated text repeats the input description. Total inference wall time for all probes is 0.598949 s. The [read-only review](../natural_io/evidence/review-text-interface-001.json) confirms hashes, finite tensors, current-caption provenance and the exact 2,573,074,432 Linear-MAC accounting. This closes the narrow text encoder/decoder interface condition, not translation, semantic quality, shared multimodal generation or NDU benefit.

The final [DAC audio receipt](../natural_io/evidence/audio-codec-003.json) also records an actual two-second roundtrip: waveform `[1,1,32000]` → fixed right-zero pad to `[1,1,32320]` → integer codes `[1,12,101]` → latent reconstructed solely from those codes `[1,1024,101]` → decoder output `[1,1,32312]`, retaining the first 32,000 samples. Code values range from 0 to 1022; output is finite. Model code is pinned to `c7cfc5d2647e26471dc394f95846a0830e7bec34`, original weights to release `0.0.5`; all 74,175,906 parameters are frozen. Final loading explicitly uses `weights_only=True`, validated constructor metadata and strict state loading without missing/unexpected keys or unsafe fallback.

The history is preserved: [001](../natural_io/evidence/audio-codec-001.json) failed the output-length check and did not record an exact decoded length; [002](../natural_io/evidence/audio-codec-002.json) applied the fixed 320-sample right-zero guard with no left crop or reference-dependent shift/gain fitting; [003](../natural_io/evidence/audio-codec-003.json) adopted the explicit safe-loading path. [Independent verification](../natural_io/evidence/audio-codec-independent-verification.json) confirms all seven saved 002/003 artifacts are byte-for-byte identical and separately confirms the architecture's 31,992-sample output for a 32,000-zero upstream boundary probe. The latter is not presented as a measurement retrospectively recovered from 001.

DAC's same-index float32 MSE is 0.0203313247652315 and SNR is **−2.392409 dB**, before PCM rounding and without shift/gain optimization. Final execution took 5.45583 s wall / 10.68806 s process CPU with four Torch threads, excluding installation/download. The negative samplewise SNR remains visible; neither perceptual quality nor corpus-level performance is established. This completes the single-fixture audio codec interface, not target-blind audio generation or natural NDU training. See the [combined interface README](../natural_io/README.md) for provenance, reproduction and scope.

## 3. Concrete dataset route

### Primary candidate: a licensed Ego4D audio/narration subset

Ego4D supplies real egocentric videos and human written narrations; only portions have accompanying audio. The official annotation specification describes annotators writing English sentence narrations. An audio-presence check is mandatory rather than assuming every video has sound. [S3–S4]

Ego4DSounds is a useful selection/indexing route because its authors describe clips with high action/audio correspondence and timestamped narrations. Its repository identifies `train_clips_1.2m.csv`, `test_clips_11k.csv`, `ego4d.json`, `dataset.py` and `extract_ego4d_clips.py`; metadata fields include video ID, temporal boundaries, narration origin, text and noise-related fields. These are concrete assets to request, not already available local files. [S5–S6]

**License gate:** Ego4D media and annotations require the official executed data agreement and issued credentials. The public start guide documents that process and subset selection. The GitHub tools' MIT license does not license the underlying media. A publicly hosted draft agreement is not the executed agreement for this project, and the actual access form returned HTTP 403 to this research tool. Do not label Ego4D globally “CC”, “MIT data” or simply “noncommercial”; retain the executed agreement and applicable collection terms. [S3, S7]

No separate license grant for Ego4DSounds metadata/scripts was visible in the inspected repository. Obtain a recorded license basis for those derivatives, or select windows directly from the official licensed Ego4D annotations. Do not treat a visible CSV or an unofficial mirror as permission to redistribute it. This is a concrete missing artifact, not an instruction to accept an agreement on the user's behalf.

MSR-VTT is an alternative source of human captions and original audiovisual clips, but its original paper's availability of audio is not a present-day license/availability receipt for a particular downloaded clip. It is not selected until original media rights and availability are resolved. [S8] Generated-caption corpora, class labels rewritten as sentences, TTS created from captions, and videos animated from photographs are excluded from the natural-four-output evidence.

### Data unit and provenance

One eligible event needs an original recorded video with a real audio track and an existing human annotation that applies to its target interval. A proposed pilot uses a one-second observed prefix plus a two-second target continuation. Preserve source PTS, audio start offset, exact crop boundaries and both original and processed hashes. Exclude windows whose annotation/event alignment is unverified rather than inferring that an annotation timestamp defines a precise interval.

| Field | Required content |
|---|---|
| Identity | `sample_uid`, original `video_uid`, `session_uid`, available participant/camera-wearer ID, collection/site |
| Rights | Source URL/UID, author/provider, exact applicable license receipt digest, permitted use/redistribution scope |
| Video | Original recorded clip; target eight actual frames over two seconds at 128×128, plus original timing metadata |
| Audio | The same interval's original recorded waveform, resampled to 16 kHz; retain channel and synchronization metadata |
| Image | A target-interval frame with source timestamp; explicitly labeled `sampled_video_frame`, not independent still photography |
| Text | Human narration, annotator/source pointer and language; keep generated instructions separate from reference text |
| Split | Group assignment, split-policy digest, source-content hashes and duplicate-cluster ID |
| Availability | Per-modality observation mask and reveal time; targets live in an evaluator/training-only object |

The main task is **conditional natural audiovisual continuation with four typed outputs**: a human-language description, recorded-sound prediction, a future still frame and a future temporal clip. Natural targets are not evidence of four independent sensors. If the intended claim requires independent natural still photographs as well, collect or license synchronized still photographs; this candidate does not close that stronger condition.

For text-conditioned trials, the input description and output reference cannot be the same string. Use a separately obtained human annotation of the observed context or exclude that input mask. Never create an input by reading a heldout target caption and then call the output an independent caption prediction. A first AV-prefix task does not alone validate arbitrary all-modal input permutations.

### Split and acquisition budget

Proposed next pilot, to be preregistered before its heldout data are used: 6,000 training events, 512 development events and 1,024 confirmation events, three training seeds. These counts are an experimental design proposal, not a claim that enough eligible licensed records are currently available.

- Split whole participant groups when IDs permit; otherwise split whole recording/session groups and expressly retain the unresolved person-generalization limit. Keep all crops, audio, sampled frames, annotation tracks and duplicates of a source in one split.
- Require at least 30 distinct source groups in confirmation. Prevent overlapping windows or near-identical source recordings from crossing splits. Common short action phrases alone are not proof of duplicate media.
- Keep the publisher's heldout pool separate when usable; select development groups only from the publisher's training pool. Store the exact inclusion/exclusion list and deterministic group split before training.
- Select eligible IDs before downloading media. Request a bounded subset or an authorized prepared bundle, not the full multi-terabyte dataset. Start with a 50 GB workspace cap; actual required bytes must come from a manifest, and exceeding it triggers a revised acquisition plan before download.
- No heldout target is available to online feedback, candidate ranking, normalization, gain calibration or early stopping. Normalizers and codec versions are frozen from training/development records.

## 4. Specific pretrained components and integration gaps

These are reusable components, not a ready four-output foundation model. TAESD, T5 and DAC have now been loaded and exercised in separate checks on one natural fixture. Their shared conditional generation, temporal modeling, natural training and independent-data validation remain unimplemented or untested.

| Adapter | Concrete upstream asset | License evidence | Intended use and limit |
|---|---|---|---|
| Text | `google-t5/t5-small`, tokenizer/config plus one safetensors checkpoint | Model card: Apache 2.0; approximately 60M parameters. The listed safetensors file is 242 MB. [S9] | Encoder, decoder and bounded generation executed on the human description. A trained projection must still connect shared multimodal state to its decoder context; no audio/video understanding is established |
| Image | `madebyollin/taesd`, both encoder and decoder | Author repository: MIT; provides learned encoder/decoder weights and exact latent conventions. [S10] | RGB `[0,1]` ↔ latent `[4,H/8,W/8]`; count every convolution and preview. It is a codec, not a text-to-image generator |
| Audio | Descript Audio Codec **16 kHz**, author's original release `0.0.5`; code commit `c7cfc5d2647e26471dc394f95846a0830e7bec34` | Project explicitly releases weights under MIT. Exact source/license/weight hashes are in the final audio receipt. [S11] | Real two-second waveform → 12 integer codebooks → code-derived latent → decoded waveform executed. Native hop is 320; fixed right padding handles the boundary. SNR −2.392409 dB; no caption-to-speech or unseen-audio prediction |
| Video | Apply the same image codec to each genuine source/target frame; add a learned temporal adapter and temporal loss | Same codec license; no separate video prior is claimed | Eight independently predicted frame latents form an actual temporal output. Repeating a decoded still is a failing baseline, not successful video generation |

The TAESD author explicitly notes that independent frame decoding can flicker; this is a measurable limitation for the pilot. A dedicated video codec can be a later declared replacement with its own pinned assets and new controls. [S10]

For the future natural-generation experiment, create `model_assets.json` with upstream revision, exact file URLs, byte sizes, SHA-256 digests, licenses, model config, tokenizer version, native sample rates, image scaling and runtime package lock. The completed smoke receipts already contain their narrower asset manifests. Download only the selected checkpoint format: the T5 repository also contains duplicate framework formats. No invented weight hashes or unverified package-version compatibility should enter the manifest.

The DAC mirror card inspected during research had an incomplete license field. The completed audio check instead uses the author's original GitHub release, preserves the explicit model-weight license statement and hashes, and does not rely on that mirror's missing license field. [S11]

## 5. Adapter and generation interface to implement

New code belongs in a separate `experiments/natural_output_portfolio/` package. The interfaces below are proposed contracts, not currently implemented APIs:

```python
@dataclass(frozen=True)
class NaturalRecord:
    sample_uid: str
    source_group: str
    source_manifest_sha256: str
    text: HumanAnnotation
    audio: TimedWaveform
    image: TimestampedFrame
    video: TimedFrameSequence
    provenance: ModalityProvenance

class NaturalInputAdapter:
    def encode(self, observed: ObservedBundle, ledger: WorkLedger) -> ContextTokens: ...

class NaturalGenerator:
    def initialize(self, context: ContextTokens, rng: GenerationRNG,
                   budget: ComputeBudget) -> GenerationState: ...
    def feedback(self, state: GenerationState, ledger: WorkLedger) -> PublicFeedback: ...
    def refine_step(self, state: GenerationState, control: StepControl,
                    rng: GenerationRNG, ledger: WorkLedger) -> GenerationState: ...
    def preview(self, state: GenerationState, modalities: tuple,
                ledger: WorkLedger) -> PreviewBundle: ...
    def emit_all(self, state: GenerationState, ledger: WorkLedger) -> EmissionReceipt: ...

class NaturalEvaluator:
    def score(self, sealed: EmissionReceipt, targets: TargetBundle) -> ExternalScores: ...
```

`ObservedBundle` contains only revealed input segments. `TargetBundle` must not be passed to the generator, critic or native decision API. Encoder caches require a digest of their source bytes, mask and codec revision; a cache of a hidden target is still leakage.

A concrete small backbone is a four-layer, width-256 shared temporal transformer with modality/time embeddings and separate text/audio/image/video output projections. For 128×128 visual frames, patch 2×2 blocks of the 4×16×16 codec latent into tokens: eight video frames use 512 tokens and a separate still uses 64. Audio token count comes from the pinned codec; caption length is capped at 32 tokens. Count trainable parameters after implementation rather than advertising a guessed parameter total.

The initial latent is predicted from observed inputs and ordinary generation randomness. It must not be an already-correct target latent plus compulsory removable noise. The true clean target is available only for training/scoring. A source-only depth-zero baseline must be allowed to win; do not cap its quality, reward continued steps or impose a minimum generated depth to make control look useful.

Train conditional latent prediction/flow or denoising from natural targets, followed by global utility optimization. Frozen codec decoders remain differentiable with respect to generated latent inputs. Text sampling is discrete: teacher-forced cross-entropy is a supervised surrogate; exact edit/semantic rewards require an explicitly specified score-function estimator or separately labeled approximation. Do not silently differentiate argmax or call a reconstruction anchor the NDU contribution.

The first controller can retain native STOP/REFINE with a joint latent update. It reads current state, prediction disagreement, estimated value and any paid previews. A learned value head is trained on training rollouts and calibrated only on development data. It must not use true future loss at inference. Enumerating or decoding candidate futures incurs cost, including rejected candidates; “offline” is not “free”. Modality-specific portfolio reallocation requires an extended action contract and its own acceptance evidence.

Freeze codecs initially and train the shared generator, value/policy heads and modality projections. Record utility-only and auxiliary gradients separately for each trainable group. This stage does **not** establish end-to-end NDU encoder learning. A later stage must unfreeze the intended encoder/decoder blocks and independently test that stronger claim.

## 6. Compute and execution envelope

Current CPU has completed the input smoke, pretrained TAESD image/video-frame codec checks, pretrained T5 encoder/decoder/bounded-generation interfaces and the real DAC integer-code audio roundtrip. It has no demonstrated capacity for the proposed three-seed natural generator training. Do not report a theoretical CPU possibility as a completed run.

The small CPU codec/interface checks proposed in the initial plan are now actual results above. They establish that the pinned components execute on the natural fixture; they do not establish a joint model, natural NDU credit or quality. Their weights were acquired externally rather than derived from the synthetic checkpoints. The next substantive integration step is the target-blind shared generator and evaluator on an independently split licensed corpus, including a temporal video model and complete generation-cost accounting.

A newly fitted network on the one Commons clip would not resolve the missing independent corpus: its frames, waveform and single file description are correlated parts of one source. Splitting that recording into artificial train/test windows cannot establish source-level natural generalization. The remaining blocker therefore includes dataset access, new generation/evaluation code and an actual independent experiment; it is not merely a missing GPU or a package-installation issue.

Planning allocation: one CUDA GPU with at least 24 GiB VRAM, 32–64 GB host RAM and 50 GB initial local working storage. This is an engineering request, not a measured memory requirement or runtime promise. Run a separate 32-event/200-update development profile first, recording peak VRAM, examples/second, decoding latency, backward cost and disk footprint. Then freeze the training update count and GPU-hour cap before confirmation; do not weaken gates after seeing heldout results.

The asset request is concrete:

1. An executed Ego4D data license or an equivalently authorized natural paired-media bundle, plus the precise source/annotation manifest and any required derivative-metadata permission.
2. A reproducible bundle or reacquisition manifest for the three pinned upstream components and compatible dependency lock. TAESD, T5 and DAC assets/runtimes now exist locally with execution receipts; shared natural-generation integration and its runtime/compute profile remain unimplemented.
3. An actual GPU endpoint with job/account access and enough persistent storage; no such device is present in the inspected runtime.
4. Independent human ratings for the final natural-output comparison, or an explicitly narrower metric-only claim. The evaluator and its reference texts cannot double as the generator's training reward oracle without disclosure.

## 7. Proposed acceptance gates and evidence

These gates are for a future preregistration. A plan, pretrained model download, codec round trip or successful unit test does not satisfy a generation or empirical-benefit gate.

| Gate | Required artifact / test | Current status |
|---|---|---|
| N0: natural input I/O | Licensed original with verified tracks; actual nonempty audio/frame/video/text tensors; hashes and transformations | **Passed narrowly for one Commons fixture**, receipt linked above |
| N1: licensed paired corpus | Executed applicable terms, exact frozen records, original-media hashes, human-caption provenance and disjoint source-group split | Missing |
| N2: codec/adapter integration | Real encode/decode on all eligible types; exact dtype/range/time checks; codec reconstruction reference; no model-size or modality relabeling shortcut | **TAESD image/video-frame, T5 text and DAC audio interfaces executed separately on one fixture**, with recorded limitations; no temporal video model, shared natural generator or corpus-level interface/quality validation |
| N3: target-blind four-output generation | All four outputs generated from permitted context; no retrieved target/raw file copying; no repeated-still video substitution; emitter sealed after complete output | Not implemented |
| N4: direct global training credit | Utility and auxiliary gradient receipts for shared refiner and all admitted output projections; stable-policy/estimator finite checks; encoder freeze scope explicit | Not run on natural data |
| N5: useful online feedback | Actual intermediate state changes affect decisions for comparable contexts; no future-reference leakage; hard budget and complete-output violations zero | Not run on natural data |
| N6: natural empirical advantage | New heldout comparison, matched baselines, complete compute receipts and independent quality evaluation | Not run |
| N7: foundation/end-to-end claim | Appropriate scale, broad independent natural tasks and datasets, intended encoder training credit, generalization beyond one action corpus | Remains a separate open research requirement |

For N6, suggested controls are: no refinement, validation-selected fixed depth, myopic control, dynamic continuation, matched supervised training and full-context upper-information reference. Codec reconstruction using the actual target is only a diagnostic reference and must never compete as a normal conditional generator.

Use a frozen external composite with separate text/audio/image/video errors and explicit development-set normalizers. The old eight-class prototype/argmin metric is inapplicable. A transparent initial composite can use normalized text edit distance, multi-resolution audio spectral discrepancy, image reconstruction discrepancy and temporal video discrepancy, each bounded and separately reported. These paired-reference metrics can penalize valid alternatives and reward blur/averaging, so require blinded human checks for semantic adequacy, audible events, motion and cross-modal agreement; do not claim natural fidelity from pixel/spectral loss alone.

Proposed primary success: dynamic versus the best validation-selected fixed-depth baseline improves the frozen mean composite by at least 0.02, paired source-group/seed bootstrap CI upper endpoint below zero, actual online compute ratio at most 1.10, zero data-access/budget/output-contract violations, and no material per-modality or human-quality regression under preregistered margins. These are candidate margins to freeze after development/power assessment, not retroactive gates or claimed results.

The nondegeneracy report should include actual refine fraction, depth distribution, decisions under differing observed intermediate states, and utility-only gradient coverage. A provisional 5%–95% refine-fraction gate and finite nonzero utility gradients in at least half the recorded updates make failure visible; they must not be enforced by the policy or loss. If depth zero is best, report that outcome without adding artificial disturbances after the fact.

Bootstrap whole original-source groups and training seeds; crops from one recording and repeated evaluation masks are correlated observations. Three seeds give limited training-variability evidence. Natural pilot success would close a narrow natural-data mechanism claim, not a general all-modal foundation-model claim, global neural optimality or a general continuous FBSDE solution.

## Sources inspected

All web references below were inspected on 2026-10-23. They establish dataset/model provenance and access descriptions; the proposed architecture, counts, resource envelope and acceptance margins are our experimental design, not upstream claims.

- **S1** [Commons source file and attribution](https://commons.wikimedia.org/wiki/File:Lachender_Hans_(Tierpark_Zittau).webm).
- **S2** [Creative Commons BY-SA 4.0 terms](https://creativecommons.org/licenses/by-sa/4.0/).
- **S3** [Ego4D official access and subset guide](https://ego4d-data.org/docs/start-here/).
- **S4** [Ego4D annotation guidelines](https://ego4d-data.org/docs/data/annotation-guidelines/) and [original paper](https://arxiv.org/abs/2110.07058).
- **S5** [Ego4DSounds author project](https://ego4dsounds.github.io/).
- **S6** [Ego4DSounds author repository and metadata schema](https://github.com/Ego4DSounds/Ego4DSounds).
- **S7** [Official publicly hosted draft Ego4D agreements](https://ego4d-data.org/pdfs/Ego4D-Licenses-Draft.pdf), distinguished from the executed agreement required for access.
- **S8** [Original MSR-VTT paper](https://openaccess.thecvf.com/content_cvpr_2016/papers/Xu_MSR-VTT_A_Large_CVPR_2016_paper.pdf).
- **S9** [T5-small model card](https://huggingface.co/google-t5/t5-small) and [listed checkpoint files](https://huggingface.co/google-t5/t5-small/tree/main).
- **S10** [TAESD author repository, license, latent conventions and video limitations](https://github.com/madebyollin/taesd).
- **S11** [Descript Audio Codec author repository, explicit weights license and APIs](https://github.com/descriptinc/descript-audio-codec).
