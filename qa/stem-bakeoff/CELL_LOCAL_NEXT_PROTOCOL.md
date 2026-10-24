# Local next stage: source coverage, actual operations and multimodal learning

Date: 2026-10-24. The user explicitly excludes remote CI from this phase.
Original implementation `9b1f52cd8aa11de1ec447b116c1a0258ee5f861b` and published
report `4b3081c25af86f707a5c0d50c688c959a04af446` remain unchanged. All new work is
additive. Local tests, actual execution and sealed artifacts are the evidence.

## Questions and closure evidence

| Question | Required local evidence |
|---|---|
| Does prefix truncation hide useful source information? | Full original-source bank, every native content token covered by bounded overlapping windows, versioned local/global features, exact span recovery, actual repeated encoding and storage costs. |
| Do tiny heads learn actual operational outcomes? | Fixed public buggy/fixed revisions, identical fixed tests and fixtures, actual command outcomes, phase-aware failures, whole-repository holdouts and independent bug groups. |
| Can regularization/calibration avoid the old overconfidence failure? | Train/tuning/calibration separation, prior-only escape, converged scale/bias fits, immutable pre-evaluation choices, all alternatives and parameter controls reported. |
| Does one shared owner support learned image/audio tasks? | Published real media labels, source-isolated sampling, label-free neutral text, actual image/audio tower forwards, cheap content baselines, fixed-head missing-modality controls. |
| Can the resulting tasks be served economically? | Count genuinely defined targets separately from replicas; bind features and task/model state; batch only compatible heads and include caches, retrieval, routing, training and source retention. |

Completing the measurement closes an implementation or evidence gap. A failed
quality hypothesis is a negative result, not a passed learning gate. No task is
qualified by its name, parameter count, physical replica count or test fixtures.
No universal encoder or universal head winner is assumed.

## Fixed learning analysis

`CELL_CALIBRATED_PROTOCOL.md` and its source-hashed preparation plans define the
common 8/32/128 independent-group budgets, seeds, training search, calibration,
metrics and controls. Every arm is retained even if a constant prior wins the
tuning selector. NLL improvement alone is insufficient to establish task
learning; report discrimination, balanced accuracy and positive recall together.
The budget counts selected gradient-training examples. Stratified sampling also
uses the available training pool's labels, and fixed tuning/calibration cohorts
have additional labels. Report all four counts separately, including scoring-only
holdout labels; these experiments never claim8 or128 total annotations.
Abstention is never a successful task outcome. Compare learned arms with the
strongest applicable fixed-budget baseline as well as the explicit prior.

Old repair-shape labels remain one correlated proxy family. Full-source scores
on its previously observed holdout are repeated-use diagnostics. New operational
repository holdouts and original image/audio holdouts have separate identities.
There is no heldout-dependent model/target selection. Preparation is sealed for
all declared targets before evaluating a feature condition. Any post-evaluation
change requires a new labeled exploratory condition, preserving original results.

## Real media conditions, selected before feature scoring

Images use the author-hosted CIFAR-10 binary archive with published MD5
`c32a1d4ab5d03f1284b67883e8d87530`; its SHA256 is recorded after acquisition.
Exact RGB duplicates crossing official train/test partitions and conflicting
pixel labels are excluded. One source per pixel group is selected by a fixed
salted source hash. Train uses32 examples per vehicle class and16 per animal
class; calibration uses8/class and holdout16/class from the original test split.
The four binary tasks are animal, mammal, road transport and air/water transport.
These are correlated recognition targets, not four independent skills.

Audio uses ESC-50 commit `33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6`, its metadata
labels and five published coarse categories. Entire original-recording groups
crossing official folds are excluded; one clip per original source is selected.
Folds1–3 supply at most8/class for train, fold4 at most2/class for calibration,
fold5 at most4/class for holdout. Source shortfalls are recorded, never replicated.
Every WAV must match the pinned Git blob, metadata size and complete five-second
PCM waveform. The selected690 clips contain399/99/192 train/calibration/holdout
rows, and every category supports all three balanced budgets.

Encoder prompts are exactly `A photograph.` and `An environmental audio
recording.` Category names, source paths, split names and labels never enter the
model text. Full input identities bind neutral text, modality and verified media
content. Source names are provenance only. Exact/BM25 on identical neutral text
are modality-inappropriate controls, not competitive media retrieval methods.

The common EG2 full owner uses FP32 CPU,4 Torch threads, native70 vision soft
tokens and maximum1024 text-side tokens. This budget is a distinct preprocessing
identity from the earlier280-token smoke test. All native image/audio processing
configuration and DSP array bytes are hashed. Only global features are retained
for these recognition tasks; no box/time alignment is claimed. The original
media remain available for later local-detail evaluation.

Cheap controls are all3072 RGB values scaled by `x/127.5-1`, and80 MFCC mean/std
features over the full five-second16kHz audio (40 coefficients, FFT512,
hop160,64 mel bins). Their costs and private head widths differ and are reported.
The missing-modality control substitutes the same owner's neutral-text-only
global for heldout rows while preserving each fitted head and calibrator.

Unknown pretraining overlap limits claims to transfer on these fixed datasets.
CIFAR-10 recognition is not document OCR or arbitrary visual reasoning. ESC-50
environmental sound recognition is not speech understanding or audio generation.
The upstream ESC-50 research license and per-file license information accompany
the evidence; this experiment does not establish commercial data rights.

## Operational tasks

The separately sealed BugsInPy protocol uses199 fixed bug groups from8 projects:
148 train,12 calibration and39 holdout, with entire repositories in one split.
All389 distinct pinned revisions are acquired before execution. Same fixed
revision test tree/fixtures run against both implementation states. Ordered
candidate diagnostic commands are fixed independently of observed outcomes.
Import/setup/collection/time-limit failures are typed unavailable; they are not
treated as failing assertions or useful diagnostics. Missing128-group support
stays unavailable. The scope is prediction with supplied change regions and test
context, not hidden fault localization or autonomous repair generation.

Before any operational model score, uniform repository-level dependency repairs
were exhausted and the final v3 cohort was sealed:182 validated bug groups and
539 applicable source views. All three attempts count:1,454 test commands and174
package-build commands. Replayed repositories replace their complete previous
execution condition; there is no per-case best-result selection. Remaining
pass-to-pass or upstream setup failures remain unavailable under the original gate.
Regression has136 training groups. Diagnostic choice has131 groups,70/61 classes,
so balanced128 stays unavailable. A separately preregistered balanced122 endpoint
uses the same grid/seeds/calibration and is never labeled128.

The v3 reconciliation has279 exact source/version/text matches,248 identical-text
rows with a changed execution version, and12 new rows. A separately sealed
incremental policy may reuse immutable content tensors for the248 rows only if
native input windows/masks, pooling and owner/preprocessing identities also match.
It must create a new source/version binding, preserve the original tensor origin
and receipt, and report zero new forwards for those explicit metadata rebindings.
The old sealed event bundle is never relabeled. Changed content or model identity
cannot use that cache. This policy is distinct from exact window deduplication:
the527-row prior corpus had only3.90%/4.82% duplicate Granite/EG2 input windows,
so no new window-cache numerical condition was introduced for that small saving.

## Resource and reproducibility policy

Only one EG2 process runs at a time. Tiny CPU head jobs may overlap encoding;
concurrent wall times are labeled and must not be interpreted as isolated
hardware benchmarks. Count one shared model load per owner, actual tower/model
forwards, every attempted training path, optimizer state, retained globals,
optional chunks, source storage and restoration. Tensor bytes are not peak RSS;
energy and unmeasured allocator/metadata overhead remain unknown.
The observed container quota is8GiB memory and8 CPU cores, despite a larger host
RAM/cpuset display. Other workspace jobs share those quotas; resource observations
and contention remain in the evidence. No unrelated process or build is stopped.

On2026-10-24 an ENOSPC event interrupted media acquisition before any quality
scoring. Only verified old checkpoint duplicates/obsolete partial downloads and
an already archived restore were removed. The audio plan was regenerated into a
fresh directory; the CIFAR author download resumes with HTTP206 and requires its
complete official checksum. The full-source Granite process was not restarted.
Interrupted attempts remain visible and are not counted as completed evidence.
