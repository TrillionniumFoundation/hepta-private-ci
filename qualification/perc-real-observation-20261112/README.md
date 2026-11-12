# PERC source evidence and native owner continuation — 2026-11-12

## Decision and scope

**The real document → pinned OCR/encoder → retained Python receipt → original
native wire → diagnostic inference → durable Cell owner path executed locally.
Scientific qualification remains HOLD and adoption remains NoUpdate.**

This is a continuation of #5768, whose exact head is
`2ec44e234a7164807f41af3a79e795dd71efa179`. The added source adapter, active-decision
entry and native-owner probe are research tools. Production daemon enrollment,
distributed authority, cross-boot recovery and independent real-task benefit are
not qualified by these checks.

## Implemented behavior

- `perc1.source_capture` retains the exact image, optional original document,
  source text or DOM text, raw OCR TSV, OCR text and OCR stderr. Every artifact
  has a size/hash/path binding. OCR words retain offsets, boxes and the engine's
  confidence score; that score is not a correctness probability. Exact numbers,
  dates, punctuation and units stay in the original evidence channel.
- `perc1.browser_capture` supplies a bounded ordinary-browser source backend.
  It binds the actual Chromium executable, allowed origins, selector, viewport,
  screenshot, raw DOM, rendered text, final URL and a capture receipt. Browser
  capture runs in a fresh context with explicit origin constraints. The local
  real browser test is blocked by the host's socket policy; implementation is
  not itself a successful screenshot qualification.
- `perc1.source_entry` exposes `source-capture`, `source-read`, `source-active`
  and `source-decision-read`. It uses the existing owner and producer. Effects
  start only after the owner reserves an attempt. Failure/UNKNOWN reservations
  remain retained; UNKNOWN is a nonzero CLI result and does not authorize retry.
- `perc1.active_capture` retains the complete frozen head, bounded candidate
  catalog, original prefix, choice and quote before any ACQUIRE effect. STOP
  also has a retained decision. Cold reads recompute the original choice and
  actually verify its source sidecars. A decision does not imply completed
  execution; the owner receipt is a separate result.
- STOP and ordinary capture cannot reuse the same operation identity in either
  order. New active-evidence directory entries, files and containing directories
  are synchronized. These tests exercise process recovery, not actual power loss.
- Native qualification uses unchanged `hepta-types`, `hepta-infer-core` and
  `hepta-neuron` implementations, including `PerceptionCellEncoderV1`,
  `infer_cell_with_clock` and `CellOwnerJournalV1<FileAnchorWitnessStore>`.
  The executed native linear head is hand-authored diagnostic Q24 arithmetic.
  It is not the trained semantic MLP from #5768.

The owner enforces **attempt units**. Acquisition microcredit quotes are advisory;
the new entry does not claim to enforce complete physical or monetary cost.
Full source text is retained outside the bounded native wire. The current native
head consumes visual values, not the full OCR/DOM text.

## Actual real-source/native run

[SOURCE_NATIVE_REPORT.json](SOURCE_NATIVE_REPORT.json) is copied byte-for-byte
from the completed `perc-real-source-native-001` run. Associated records are
[SOURCE_CODE_PINS.json](SOURCE_CODE_PINS.json),
[SOURCE_TRAINING.json](SOURCE_TRAINING.json) and
[SOURCE_NATIVE_FILES.json](SOURCE_NATIVE_FILES.json).

| Item | Observed execution |
| --- | --- |
| Frozen backbone | MobileNetV3-small, official checkpoint, CPU |
| Projection preparation | First 8 lexicographic TRAIN images, 4 neutral 16×16 crops each; 8 actual batches, 32 feature rows |
| Projection fit | One actual 16-dimensional PCA; no neural gradient updates |
| Ordinary source | Ninth TRAIN image, `0001239897.png`, 51,858 bytes |
| Online capture | One callback, one real Tesseract invocation, one actual MobileNet batch |
| Exact evidence | Five retained artifacts, 39 OCR spans; all read back and hash checked |
| Source CLI replay | Same receipt and budget; zero capture callbacks, model loads or encoder calls |
| Source CLI cold read | Same result after deleting this run's input/weight copies; zero new work |
| Native handoff | Exactly the original 15,632 wire bytes; no reconstructed substitute |
| Native checks | 13 separate child invocations meet their expected assertions |
| Independent real task benefit | 0; this is one engineering source image |

Original image SHA-256:
`e3a77b696f0ff82c3ff96a82711f178e4feae835775eaecd529ae7b549818bb6`.
Original wire SHA-256:
`be55d8f58db074d91a75618b29fd853c73d6b53f50a9d1dc14518e456175e915`.

The 13 native invocations comprise eight expected exit-zero outcomes (including
pending outcomes) and five expected nonzero refusals. They cover initial commit,
three completed cold replays, lost ACK, original-receipt loss/tampering/recovery,
source/head drift, frontier rebinding, journal rollback against the witness and
read-only refusal without an original admission. The actual diagnostic head ran
twice. Pending receipt recovery validates the original native input but does not
rerun MobileNet or the head. Only the three completed cold replays have zero
native encoder/head/readback calls together.

The independent audit rechecked all 16 source byte pins and 151 retained files,
compared the original wire at every handoff and independently recomputed the Q24
head output. This is local integrity evidence, not hardware attestation.

### Measured cost

| Measurement | Wall time |
| --- | ---: |
| First ordinary source CLI process | 5.435555 s |
| Source CLI replay process | 0.188579 s |
| Source CLI cold-read process | 0.114 s (rounded) |
| Native qualification command, including 13 child checks | 1.532 s (rounded) |
| First OCR stage, inside the first source CLI | 0.599184 s |
| Encoder cold load, inside the first source CLI | 3.627107 s |
| Online backbone forward, inside the first source CLI | 0.030767 s |
| PCA fit | 0.198551 s |

Nested stages overlap and must not be summed. The driver's internal 12.518-second
timer excludes top-level imports/startup and its final report/manifest writes.
Separate process envelopes retain observed wall, waited CPU, RSS and raw streams.
RSS is the recorded process high-water mark, not incremental model memory or a
simultaneous process-tree peak. Earlier scanning/rendering, download, energy,
provider billing and full physical-process-tree costs are not measured.

Cold read still requires the retained owner, configuration, projection and pinned
source version. Deleting this run's image/weight copies does not establish
recovery from arbitrary artifact loss or a reboot. OCR output remains unverified
transcription; origin authentication and source-group independence remain false.

## Actual active source CLI run

[ACTIVE_REPORT.json](ACTIVE_REPORT.json) records `PASS_LOCAL_ACTIVE_PIPELINE`.
The next TRAIN document, `0001438955.png`, supplies a 64×64 initial crop and a
128×128 crop containing it, at a fixed neutral page position. Original-page and
pixel-crop mappings were checked and retained. No annotation or held-out source
was read. This run reuses the already frozen projection.

| Operation | Result | New capture / model load / encoding | Process wall |
| --- | --- | ---: | ---: |
| Initial source | executed | 1 / 1 / 1 | 4.260278 s |
| ACQUIRE expanded ROI | executed | 1 / 1 / 1 | 4.049307 s |
| STOP | stopped | 0 / 0 / 0 | 0.152697 s |
| Two decision cold reads | original choices verified | 0 / 0 / 0 each | 0.113451 / 0.092248 s |
| ACQUIRE / STOP replay | original receipt/choice verified | 0 / 0 / 0 each | 0.113995 / 0.101813 s |
| Ordinary capture using STOP token | expected exit 2 | no new owner operation | 0.152949 s |
| Fresh token after cap exhausted | expected exit 2 | no new owner operation | 0.143805 s |
| Final source cold read | original receipt verified | 0 / 0 / 0 | 0.091718 s |

All ten subprocess measurements are valid; the complete outer command took
9.591915 seconds. The attempt cap is two, with two reserved and zero remaining
at completion. Replays leave that state unchanged. Before cold reads, this run's
input/weight copies were moved to a retained alternate directory, leaving their
configured acquisition paths absent. Original inputs remain untouched.

The controller was fitted once to manually specified synthetic diagnostic branch
labels. Its visual feature coefficients are explicitly zero. It exercises the
ACQUIRE/STOP decision contract and actual geometric ROI expansion; it cannot
establish learned visual value, terminal quality or net benefit. The report
therefore records zero real value-training pairs, zero independent real tasks,
null terminal quality/net benefit and NoUpdate.

Associated records: [ACTIVE_COMMAND_ENVELOPE.json](ACTIVE_COMMAND_ENVELOPE.json),
[ACTIVE_CODE_PINS.json](ACTIVE_CODE_PINS.json),
[ACTIVE_FILES.json](ACTIVE_FILES.json),
[ACTIVE_SOURCE_MAPPING.json](ACTIVE_SOURCE_MAPPING.json) and
[ACTIVE_DIAGNOSTIC_CONTROLLER.json](ACTIVE_DIAGNOSTIC_CONTROLLER.json).

## Real document engineering smoke

The formerly unavailable document integration input was restored from the exact
official FUNSD archive. One TRAIN document, `funsd-00866042`, actually ran the
seven existing conditions. The smoke retained 12 collector observations (10
encoded, 2 OCR-only), 13 encoder calls including three projection-preparation
calls, and four formal traces. It passed once with zero skips.

See [DOCUMENT_SMOKE_REPORT.json](DOCUMENT_SMOKE_REPORT.json),
[DOCUMENT_SMOKE_RUN.json](DOCUMENT_SMOKE_RUN.json) and
[DOCUMENT_SMOKE_FILES.json](DOCUMENT_SMOKE_FILES.json). Seven conditions are
not seven independent tasks. The heads in this smoke are diagnostic fixtures;
it does not evaluate held-out terminal benefit. The later integrated Python
regression exercises this same engineering case again, not a new source cohort.

## Prior source reuse is an explicit HOLD

The current 64/16/32 panel has the same original-document SHA groups as the
previous published real-producer experiment. An actual invocation of the existing
source-reuse guard returned exit 2 / `HOLD_REUSED_SOURCE`: 64 TRAIN, 16 DEV and all
32 confirmation groups overlap. There are **zero fresh confirmation groups**.
See [SOURCE_REUSE_SUMMARY.json](SOURCE_REUSE_SUMMARY.json) and the complete
[SOURCE_REUSE_AUDIT.json](SOURCE_REUSE_AUDIT.json).

The historical negative result already compares learned acquisition against
direct requested-ROI OCR: global-active and direct ROI both returned 24/32,
with global-active using 2.711327× the online proxy cost; dense-active returned
23/32 at 2.762103×. These are prior results, not new runs from this continuation.
See the pinned [previous report](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/2ec44e234a7164807f41af3a79e795dd71efa179/qualification/perc-real-producer-20261109/README.md).

No new confirmation campaign was executed on those reused documents. A new
scientific comparison needs new app/document-source groups, frozen train/dev
choices, strong rule/OCR and public-feature controls, and terminal outcomes under
matched observation opportunities. A seed, runtime change or repeated read does
not create a new independent task. Temporal-head benefit and native execution of
the trained semantic model remain untested here.

## Regression and environment gate

The integrated local run executed 149 PERC tests: 146 passed, two newly composed
source fixtures errored because their exact-text fields were incomplete, and the
actual Chromium screenshot case errored at the host socket gate. The fixtures
were corrected to carry real retained text bytes, without weakening validation;
both targeted cases then passed. The original full-run errors remain preserved.
There was no second complete local regression after those fixes.

See [VALIDATION.json](VALIDATION.json),
[local-regression-first.log](local-regression-first.log) and
[local-fixture-correction.log](local-fixture-correction.log). A separate earlier
browser run also had one binary-pin rejection PASS and one actual screenshot
ERROR. The local browser outcome is blocked, not skipped or silently green.

The scoped hosted workflow checks out the exact candidate head, installs pinned
CPU/model/browser prerequisites, runs every PERC Python case and requires the
real document, producer, OCR and browser tests to actually pass. It then builds
and runs the ordinary source/native and active source qualification drivers.
Its observations and exact source SHA are recorded separately; configuring the
workflow does not establish a hosted PASS. Raw hosted inputs remain runner-local;
the uploaded summaries/manifests have a 14-day retention period.

## Reproduce the ordinary source/native path

Use a fresh output directory for each attempt. Preserve failures and UNKNOWN
states. The CI input helper downloads the pinned official archive/checkpoint,
rejects unsafe ZIP members and prepares the same explicitly reused engineering
panel. It does not claim new confirmation data.

```bash
PYTHONPATH=scripts python scripts/perc1_ci_inputs.py --output "$PERC_NEW_INPUT_DIR"

PYTHONPATH=scripts python scripts/perc1_native_owner_probe.py \
  --repo "$PWD" --source-ref "$PERC_SOURCE_COMMIT" \
  --build-dir "$PERC_NEW_BUILD_DIR" --cargo "$PERC_CARGO" --rustc "$PERC_RUSTC" --online

PYTHONPATH=scripts python -m perc1.source_qualification \
  --training-images "$PERC_NEW_INPUT_DIR/funsd/dataset/training_data/images" \
  --acquisition-manifest "$PERC_NEW_INPUT_DIR/funsd-acquisition.json" \
  --weights "$PERC_NEW_INPUT_DIR/mobilenet_v3_small-047dcff4.pth" \
  --weights-sha256 047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f \
  --native-binary "$PERC_NEW_BUILD_DIR/target/debug/perc1-native-cell-probe" \
  --output "$PERC_NEW_SOURCE_RUN"

PYTHONPATH=scripts python -m perc1.active_source_qualification \
  --prior-run "$PERC_NEW_SOURCE_RUN" \
  --training-images "$PERC_NEW_INPUT_DIR/funsd/dataset/training_data/images" \
  --weights "$PERC_NEW_INPUT_DIR/mobilenet_v3_small-047dcff4.pth" \
  --output "$PERC_NEW_ACTIVE_RUN"
```

The repository retains source, aggregate results and full-byte provenance.
Original FUNSD images/crops, OCR payloads, real wire/RGB and owner journals belong
in the private evidence package, not the public Git repository. Hosted artifacts
contain only selected summaries, case-status/compiler logs and hash/size lists;
their presence is not a successful engineering or scientific gate.

The first hosted run on `d411c36` failed before creating any jobs. Source review
found six `runner.temp` expressions at job-env scope, where GitHub does not allow
the runner context. The correction moves those bindings to step-env scope and
exports them through `GITHUB_ENV`, with independent bindings for the always-run
failure reporter. The corrected export and early-failure reporter were executed
in isolation; a new platform run is required to establish hosted execution.
The original failure and the context review remain in
[CI_STARTUP_FAILURE.json](CI_STARTUP_FAILURE.json) and
[CI_CONTEXT_REVIEW.json](CI_CONTEXT_REVIEW.json). Earlier YAML/shell syntax checks
did not establish GitHub Actions context validity.

The completed private package has 782 members and 39,224,877 bytes. All 780
original-file entries were verified against their size/SHA manifest after ZIP
creation. Its SHA-256 is
`8038206cf0219ab9ea1b7547ddc74aa6041c552c2843ecd1509c26215e0744b5`.
It includes original inputs, model artifacts, real receipts/journals, command
streams, executed native binary and failed attempts, without copying the Git
repository. See [PRIVATE_ARCHIVE.json](PRIVATE_ARCHIVE.json).

[SOURCE_COMMITS.json](SOURCE_COMMITS.json) records the reviewable source stages.
Required `just fmt` passed. All 16 ordinary-source and all 17 active-source
execution pins still match the formatted files; no identical local tests were
rerun after formatting. See [FORMAT.json](FORMAT.json).
