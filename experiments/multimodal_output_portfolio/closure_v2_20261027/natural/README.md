# Natural output portfolios: bounded closure experiments

This continuation obtains new, actual-output evidence for three specific
engineering improvements. A fitted video reconstructor preserves the original
quality margin while using less CPU; a speech gate chooses its decoder before
paying for a first decoding pass; a conservative receipt decoder learns when to
change a strong rule answer. The fixed-model receipt replication establishes a
positive quality and cost-adjusted return increment over those rules.

A subsequent source-only identity audit finds that the receipt groups are not
all independent physical merchants: 128 annotation-name groups contain 126
confirmed store components, including three stores already present in earlier
experimental data. A more conservative company/family screen identifies six
overlapping images. Removing all six leaves a positive 120-component sensitivity
result, but that posthoc diagnostic is not a new prospective entity-disjoint
qualification. The original protocol and its reported result remain unchanged.

These results close the named component comparisons below. They do not establish
an optimal general multimodal portfolio, integrate the original Hepta neuron into
these natural-task adapters, or demonstrate natural speech synthesis and semantic
video synthesis. The delivered speech task is transcription, the video task is
missing-frame reconstruction, and the document task is structured OCR extraction
with an annotated image. General multimodal training and those broader generation
capabilities remain outside this component evidence.

## Results and remaining boundaries

| Component and frozen comparison | New experimental sources | Actual output result | Scope of conclusion |
| --- | --- | --- | --- |
| Efficient video versus prior learned motion mixer | 8 DAVIS sequence families; 64 target frames | PSNR difference +0.117234 dB, 95% source CI [−0.184361, +0.425250]; CPU −0.015667 s/frame, CI [−0.016581, −0.014716]; wall −0.018515 s/frame, CI [−0.020839, −0.016468] | Original −0.25 dB quality margin and actual cost gates pass. A fixed solver selected on validation; no adaptive-allocation superiority claim. |
| Video training attribution versus the same solver at its initial coefficient | Same 8 sources | PSNR +0.971631 dB, CI [+0.258125, +1.693381] | A real fitted-parameter output improvement. Identical solver structure; no speedup attributed to the scalar fit. |
| Speech encoder gate versus fixed beam 5 | 16 new speakers; 64 utterances; 1,280 reference words | WER difference +0.002344, 95% speaker CI [−0.000859, +0.005797]; CPU −0.067972 s/utterance, CI [−0.104414, −0.034029]; wall −0.067561, CI [−0.104383, −0.032458] | Original +0.01 WER margin and cost gates pass for this prespecified comparator. |
| Identical speech continuation policy with versus without encoder reuse | Same 64 utterances; 57 real continuations per repetition | All paired transcripts identical; CPU −0.970322 s/utterance, CI [−1.073286, −0.850500]; wall −0.983161, CI [−1.090866, −0.861966] | Actual duplicate-encoding removal on new sources. The continuation policy itself remains slower than fixed beam 5. |
| Receipt residual versus strong rules, first qualification | 24 new normalized merchant strings | Quality +0.017381, 95% CI [−0.000260, +0.042576] | Inconclusive. The original failed strong-baseline gate remains unchanged. |
| Same receipt model versus strong rules, one separately frozen replication | 128 further new normalized merchant strings; 512 observed fields per repetition | Quality +0.020396, 97.5% CI [+0.010327, +0.031671]; quality minus 0.01 CPU seconds +0.020291, CI [+0.010194, +0.031518] | The fixed-model replication passes. CPU difference +0.010470 s, CI [−0.007585, +0.030930]; no claim that residual scoring is faster than rules. |

All qualification records, actual media, failed comparisons, and development
candidates are retained. No new result replaces a previous failed result.
Confidence intervals resample source groups, not individual frames or timing
repetitions. They are bounded cohort measurements from this CPU host, not a
proof of population-level generalization or global dynamic optimality.

Exact values and sealed acceptance results are in the
[video result](evidence/video-qualification-001/RESULT.json),
[speech result](evidence/speech-qualification-001/RESULT.json),
[first document result](evidence/document-qualification-001/RESULT.json), and
[fixed-model replication result](evidence/document-replication-001/RESULT.json).
[GATE_LEDGER.json](evidence/GATE_LEDGER.json) records each passed and open claim
separately.

## Video: fit output quality and remove execution overhead

The previous learned mixer failed to demonstrate a stable gain over its own
initialization, and its allocation policy selected expensive motion everywhere.
This experiment therefore improves the actual fixed generator first. It fits a
single convex mixing coefficient to RGB reconstruction error on the existing
36 development frames, then compares three OpenCV DIS configurations on the
existing 18 validation frames. Selection chooses the cheapest measured candidate
within 0.25 dB of the original pure-flow validation quality. The selected solver
is DIS ultrafast with coefficient **0.9029752972422481**.

The fit is an exact constrained least-squares solution, rather than a large
neural-network update. It mixes a bidirectional motion reconstruction with the
endpoint average. Both motion directions use two inverse-map updates. The
training-attribution arm uses exactly the same DIS solver with coefficient 0.5.
Thus its pixel-quality contrast isolates the fitted mixing coefficient, while
the comparison to the previous generator also includes a change of flow solver.

| Delivered generator | PSNR dB | Mean RGB MSE | CPU s/frame | Wall s/frame |
| --- | ---: | ---: | ---: | ---: |
| Endpoint blend | 22.109878 | 0.008874939 | 0.017298 | 0.019839 |
| Original pure flow | 25.023182 | 0.006030521 | 0.040710 | 0.046565 |
| Original learned mixer | 25.007925 | 0.005944799 | 0.040948 | 0.047162 |
| Efficient solver, initial coefficient | 24.153528 | 0.005977451 | 0.025292 | 0.029090 |
| Efficient solver, fitted coefficient | 25.125159 | 0.005401992 | 0.025281 | 0.028647 |

The new sources are the first eight eligible DAVIS sequence families in the
frozen enumeration: bear, bike-packing, blackswan, bmx-bumps, boat,
boxing-fisheye, breakdance, and bus. Targets have global frame indices congruent
to 2 or 3 modulo 4; endpoints at target ±2 have indices congruent to 0 or 1.
Consequently no target frame appears as another example's public endpoint.
Frames remain temporally dependent within each source family.

The official DAVIS ZIP is accessed by bounded HTTP ranges. The archive size,
ETag, last-modified value, requested ranges, member CRCs, actual source JPEGs,
and per-file SHA-256 values are retained. A whole-ZIP SHA is not claimed because
the 832,766,765-byte ZIP was not downloaded in full. An independent auditor
rebuilds all 192 canonical endpoint/target PNGs from their source JPEGs and
reopens all 640 generated PNGs. Targets and source labels enter scoring only
after output write and readback.

David, Dudek, and Faceocc2 are development clips in the preceding continuation.
Some were held out in older, retired experiments before being explicitly moved
to development. The new frozen protocol's phrase "no historical test frame"
is therefore too absolute; `evidence/SCOPE_ADDENDUM.json` records this correction
without rewriting the frozen protocol. None of the preceding natural
qualification clips realshort, vtest, or cockatoo is used for this fit or model
selection. Only the eight new DAVIS families support the new qualification.

## Speech: decide before decoding and measure the cache separately

The previous tiny-to-base cascade selected no continuations and failed its
quality margin. This study retains one frozen base.en model and exposes both
the benefit and the cost of continuation. All candidates use the same actual
audio and model weights; there is no random or weaker-model comparator used to
manufacture a scheduling gain.

The first development experiment executes every post-decoder threshold on the
previous 24 validation utterances. The cheapest candidate that satisfies the
original +0.01 WER noninferiority margin selects threshold −0.05, continuing
23 of 24 validation cases. This nearly universal two-pass behavior reveals the
remaining decoder overhead even after correct encoder reuse.

Before fetching or generating the new qualification outputs, a separately
recorded extension adds an encoder-only gate. It uses log duration and 48
blockwise summaries of the public encoder representation. A 50-coefficient ridge
model is fitted on 24 old training utterances from eight speakers. Its target
is the observed difference in exponential utility between beam 1 and beam 5,
using utility `1 − clipped WER − 0.01 × decoder CPU seconds` and risk coefficient
2. These price and risk values are protocol choices, not estimated user
preferences. The ridge penalty is 10; the intercept penalty is 0.001.

Every candidate threshold, including fixed beam 1 and fixed beam 5, is then
actually executed on the old 24 validation utterances from eight different
speakers. The selected threshold is **−0.0007247636911868068**, with nine beam-5
decodes on validation. The gate computes one encoder representation and dispatches
exactly one decoder. Reference text and alternative decoder output are absent
from the inference interface.

| Qualification policy | Word errors / 1,280 | WER | CPU s/utterance | Wall s/utterance | Encoder / decoder calls per repetition |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fixed beam 1 | 69 | 0.053906 | 1.461311 | 1.474495 | 64 / 64 |
| Fixed beam 5 | 65 | 0.050781 | 1.581306 | 1.598997 | 64 / 64 |
| Cached post-decoder continuation | 65 | 0.050781 | 1.891424 | 1.904305 | 64 / 121 |
| Re-encoded same continuation policy | 65 | 0.050781 | 2.861746 | 2.887467 | 121 / 121 |
| Encoder-only gate | 68 | 0.053125 | 1.513334 | 1.531436 | 64 / 64 |

The encoder gate chooses beam 1 for 52 utterances and beam 5 for 12. The primary
comparison to beam 5 passes its original quality and measured cost conditions.
All five policies run twice, producing 640 actual transcript files.

The cheaper fixed beam 1 remains a substantive competitor. A separately labeled
postqualification diagnostic finds that it also meets the +0.01 WER margin on
this new cohort: WER difference versus beam 5 +0.003125, 95% CI [0, +0.006796].
The learned encoder policy reduces its error count by only one word and costs
an additional 0.052024 CPU seconds per utterance, CI [+0.004656, +0.107967].
Fixed beam 1 failed that margin on the old validation set, so it was not
selected there. The new observation is retained as evidence against a claim
that the learned policy dominates every fixed policy. It is not used to
back-select a new test winner.

Caching has a separate, valid mechanism result: 57 of 64 new utterances really
request continuation, and cached versus re-encoded execution yields identical
text with one fewer encoder invocation on those cases. However, cached
continuation versus fixed beam 5 still adds 0.310117 CPU seconds per utterance,
CI [+0.246773, +0.375490], with identical transcripts. The quality/cost gate for
that comparison remains false. Reuse removes duplicate computation; it does
not make an unnecessary first decoder free.

### One correction of the speech timing boundary

Review finds a small but concrete implementation asymmetry in the original
five-arm measurement: the original engine reopens its public JSON receipt
inside its timer, whereas the encoder gate's JSON is read back only by the
later auditor. `SPEECH_TIMER_CORRECTION_PROTOCOL.json` therefore freezes one
correction on exactly the same 64 utterances, two principal policies, and two
repetitions. The checkpoint, 50 gate coefficients, threshold, public features,
source order, encoder state, prompt, suppression list, and decoder parameters
remain fixed. No strategy is selected again and no new source is added.

Both arms now use one common function and timer: audio preparation, encoding,
the policy's necessary gate, one decoder call, the same first/final UTF8 writes,
closed-file readback, and final hash. All additional JSON writes and readbacks
occur after both stop timestamps for both policies. Their measured CPU and wall
cost are separately retained, and the study also reports a metadata-inclusive
comparison. Model loading and the same original warmup are recorded separately.
Every one of the 256 measured outputs must match its original UTF8 SHA, encoder
SHA, and beam choice. This is an execution-measurement correction, not another
independent quality qualification. The original five-arm result and cheap-greedy
diagnostic remain authoritative records of their original measurements.

All 256 corrected-timer outputs match the original transcript bytes, encoder
hashes, and decoder choices. The independently reconstructed speaker intervals
remain negative for both time measures, including all metadata work:

| Corrected common execution boundary | Fixed beam 5, s/utterance | Encoder gate, s/utterance | Paired difference, 95% speaker CI |
| --- | ---: | ---: | --- |
| CPU through actual transcript readback/hash | 1.509699 | 1.430630 | −0.079070 [−0.099537, −0.058718] |
| Wall through actual transcript readback/hash | 1.510597 | 1.431497 | −0.079100 [−0.099502, −0.058850] |
| CPU including equal metadata write/readback treatment | 1.510106 | 1.431068 | −0.079037 [−0.099497, −0.058677] |
| Wall including equal metadata write/readback treatment | 1.511002 | 1.431973 | −0.079029 [−0.099441, −0.058760] |

Exact results and verification are in
[speech-timer-correction-001/RESULT.json](evidence/speech-timer-correction-001/RESULT.json)
and [INDEPENDENT_TIMER_CORRECTION_AUDIT.json](evidence/INDEPENDENT_TIMER_CORRECTION_AUDIT.json).
The separate [peer review](evidence/PEER_TIMER_CORRECTION.json) also reopens all
256 records and independently reproduces both timing boundaries and intervals.
The unchanged bytes carry forward the original WER difference +0.002344 and
95% interval [−0.000859, +0.005797]. The two absolute timing runs occurred under
different host conditions; subtracting their absolute averages is not an estimate
of the cost of a JSON read. The new paired comparison resolves the shared-boundary
question. Fixed greedy was not remeasured or reselected in this correction, and
the earlier strong-cheap-control limitation remains.

The model is `Systran/faster-whisper-base.en`, revision
`3d3d5dee26484f91867d81cb899cfcf72b96be6c`, int8, one CPU thread. An initially
copied revision annotation was wrong and was corrected before new source
fetching or generation. Actual development always loaded the existing model
whose SHA is `2a166925539a16005f14ff328359f9b9adb9dc4fb631bb3b227526862e93e2ef`.
The original annotation, correction, protocol identities, and pretest encoder
extension are all retained. This is a metadata correction, not a change of the
executed pretrained weights.

## Documents: learn conservative corrections to a strong baseline

The previous nonlinear candidate scorer fit its training labels but produced
worse new-merchant answers than the original rules. The new decoder preserves
the rule answer as candidate zero and learns a field-specific residual quality
gain. Its input is the difference between candidate features and rule-candidate
features, plus an alternative indicator. Four ridge regressions contain 128
coefficients in total. Candidate OCR text and layout are public; no reference
box or answer enters deployment inference.

The loss matches the evaluation target: half exact match and half normalized
edit similarity, averaged over observed fields. Missing references are masked.
Fitting uses the old 24 training merchants. Validation evaluates the fixed grid
of ridge penalties and correction thresholds on the old 12 validation merchants,
using the original entropic utility and tie rules. It selects penalty **100**
and correction threshold **0.1**, changing eight of 48 validation fields.

The first new qualification executes four policies twice on 24 further merchant
strings, delivering 192 actual answer JSON / annotated JPEG pairs. The residual
quality is 0.528062 versus 0.510681 for the original rules. The 95% source interval
for their difference includes zero; that gate remains inconclusive. Relative to
the old always-refine learned decoder, the residual improves quality by 0.121613
and reduces about 2.079 CPU seconds per document. This latter improvement is
useful, but does not by itself demonstrate a gain over strong rules.

### One fixed-model replication

After that inconclusive result, exactly one larger replication was separately
authorized and frozen. It changes neither penalty, threshold, model weights,
OCR, feature construction, nor selection logic. The full candidate universe is
enumerated before output generation: 347 official test rows followed by 626
official train rows, in numeric row order. Excluding all historical, development,
and earlier qualification merchant strings leaves 207 eligible groups. The first
128 are frozen, comprising 76 official test rows and 52 official train rows
never used by this experiment. There is no quality-based inclusion or stopping.

Both policies use the same image and one actual OCR call. Residual scoring is
charged. Order rotates by source and repetition, and all 512 outputs are
completed before the single primary analysis. The primary endpoint is quality
minus 0.01 times measured process-plus-child CPU seconds. The prespecified
paired source bootstrap uses 5,000 draws, seed 2832, and a 97.5% interval. The
old 24 merchants are not pooled into this analysis.

| Policy, 128-source replication | Quality | Exact field fraction | CPU s/document | Wall s/document | Quality − 0.01 CPU |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original rules | 0.519975 | 0.408203 | 1.009547 | 1.045225 | 0.509879 |
| Frozen learned residual | 0.540371 | 0.417969 | 1.020017 | 1.055886 | 0.530171 |

The residual changes 43 of 512 fields and adds five exact fields. Its primary
increment is **+0.020291**, 97.5% CI **[+0.010194, +0.031518]**; raw quality also
has a positive interval. Thus the replication supports an output benefit
attributable to these fitted residual parameters under the same one-OCR budget.
CPU and wall differences each have intervals spanning zero. It does not establish
a speedup over rules, and no further cohort is added after seeing this result.
Descriptive quality increments are +0.026151 for the 76 upstream test rows and
+0.011985 for the 52 upstream train rows; they are not separately selected gates.

Merchant groups are normalized annotated company strings, not independently
verified corporate entities or templates. In the first cohort, for example,
the peer verified that TED HENG and TEO HENG annotations share the same printed
TEO HENG header and address. Its 23-cluster sensitivity is a posthoc diagnostic;
the original 24-string-group gate remains unchanged. Source-string and exact-image
separation are verified, while broader entity separation is not. Upstream split
labels also do not prove that a pretrained OCR system has
never encountered related receipt layouts. These restrictions remain even when
the fixed-model replication passes.

### Source identity audit and frozen sensitivity

Before archiving, a separate metadata-only audit examines all 230 source records:
18 historical documents, all 60 preceding continuation documents, the first 24
new qualification documents, and the 128 replication documents. Candidate pairs
use company-name and address similarity, exact telephone/company/GST identifiers,
and full source `reference_words`. Manual decisions examine those source fields
and printed outlet names, without consulting per-source gains. Aggregate study
results were already known, so this is explicitly a postqualification audit.
`DOCUMENT_ALIAS_SOURCE_SEAL.json` freezes the source manifests, all candidates,
two entity partitions, bootstrap choices, and code SHA before the sensitivity
code reads the output rows. A separate peer reviews this same sealed mapping.

| Experimental cohort | Documents / original string groups | Confirmed physical components |
| --- | ---: | ---: |
| Historical fit | 6 | 6 |
| Historical test | 12 | 12 |
| Continuation fit | 24 | 23 |
| Continuation validation | 12 | 12 |
| Continuation test | 24 | 23 |
| First new qualification | 24 | 23 |
| Fixed-model replication | 128 | 126 |

The replication contains two repeated-store pairs: GL HANDICRAFT and Y/YONG
SOON FATT. Three other replication images match a previous physical store:
MYDIN MART SRI MUDA / TRI SHAAS and WAN SHE / WAN SHENG occur in the fitting
data; UNIHAKKA occurs in the first new qualification. Company IDs, GST IDs,
telephone numbers where present, full addresses, and source headers support
those identities. The exact image hashes remain distinct across all 230 inputs.

The corporate/family partition adds three different cases without conflating
them with the same store. AEON shares its legal entity and registered address,
but source footers identify different PUCHONG and TEBRAU CITY outlets. GERBANG
ALAF explicitly prints its former GOLDEN ARCHES name; the company identifiers
match, while the McDonald's outlets differ. Four MR DIY records share a group
and registered address but name different outlets and carry different company
identifiers. Those MR DIY links are a conservative family/template scenario,
not a claim of legal-entity or physical-store equality.

The sealed sensitivity uses 5,000 entity-cluster bootstrap draws, seed 2844,
and 97.5% intervals. It reports both equal weight per audited entity and the
original document-weighted estimand with whole-entity resampling. The table
shows the equal-entity results; the full file contains both versions.

| Existing-output diagnostic | Images / audited components | Quality difference, 97.5% CI | Quality − 0.01 CPU difference, 97.5% CI |
| --- | ---: | --- | --- |
| First qualification, merge the confirmed alias | 24 / 23 | +0.018367 [−0.000869, +0.050063] | +0.018546 [−0.000725, +0.050199] |
| Replication, merge its repeated physical stores | 128 / 126 | +0.020720 [+0.010800, +0.032331] | +0.020608 [+0.010692, +0.032230] |
| Replication, also exclude all three prior physical-store overlaps | 125 / 123 | +0.021225 [+0.011011, +0.033328] | +0.021093 [+0.010825, +0.033236] |
| Replication, conservatively exclude all six prior physical/corporate/family overlaps | 122 / 120 | +0.021756 [+0.011258, +0.034434] | +0.021621 [+0.011071, +0.034339] |

The observed increment therefore is not explained by the identified overlapping
sources. No model is refitted, no new output is generated, no original gate is
replaced, and no cohort is added. Nevertheless, the original 128-name cohort
cannot be described as 128 previously unseen independent physical merchants.
Unflagged identity aliases and shared receipt templates may remain. A prospective
qualification using an entity registry fixed before sample selection is a
separate unresolved generalization requirement. The new source-only registry
and complete mapping make that requirement concrete rather than hiding it in
an annotation-normalization assumption.

Exact evidence is in
[DOCUMENT_ALIAS_SOURCE_SEAL.json](evidence/DOCUMENT_ALIAS_SOURCE_SEAL.json),
[DOCUMENT_ALIAS_SENSITIVITY.json](evidence/DOCUMENT_ALIAS_SENSITIVITY.json), and
the peer mapping review. The earlier peer's 23-cluster interval used 95%; the
new sealed diagnostic uses 97.5%. Their differing lower limits are not a change
to the original study or a selection of whichever interval passes.

## Timing, evidence, and audits

Reported policy times include actual input decoding, selected encoder/decoder,
flow or OCR work, controller scoring, output serialization, readback, and hashes
inside the recorded policy boundary. Process plus child CPU is used for OCR.
Video metadata writing and all speech receipt writes are included. Every speech
arm reads back its actual delivered transcript. The four original-engine speech
arms also read back the JSON receipt inside the timer; the encoder gate's JSON
receipt is reopened by the later auditor. Thus receipt-validation bookkeeping is
not identical across those implementations. Document final public-result
bookkeeping is outside its returned timer. Output directory
creation precedes these timers. Process/model startup, network fetching, common
source preprocessing, private scoring, and statistical analysis are excluded
from per-policy times and are not presented as free deployment work. These
serial measured policy times are not full service startup or network latency.
The previous cascade's amortized offline throughput is a different quantity and
is not substituted for these observations.

Each scientific run has an immutable `FROZEN_REGISTRATION.json`, checkpoint
copies, and an `executed-source` snapshot. Later audit and packaging helpers do
not retroactively change the executed code. `evidence/SCOPE_ADDENDUM.json`
qualifies overly broad wording without altering original protocols or outcomes.
The declared evidence is based on experiments recorded here; no analytical NDU
optimality theorem or global HJB solution is inferred from these measurements.

`audit_outputs.py` independently reopens all first-qualification media, decodes
the speech FLAC files, reconstructs canonical video frames, and recalculates
quality, edit distance, call counts, and source-level intervals. It imports no
experiment scorer or generator. `audit_replication.py` additionally verifies
all 512 replication JSON/JPEG pairs, all prior exact-image exclusions, full
enumeration order, frozen N and model identity, delivery chronology, and the
97.5% primary interval. The receipts are
`evidence/INDEPENDENT_OUTPUT_AUDIT.json` and
`evidence/INDEPENDENT_REPLICATION_AUDIT.json`.

The separate peer auditor imports none of the producer's scorer, statistics, or
auditor. It reopens all 1,984 qualification deliveries and independently checks
the score intervals, complete grids, frozen model/source identities, and speech
encoder hashes. Its passing receipt and exact executed source copy are
`evidence/PEER_NATURAL.json` and `evidence/PEER_NATURAL_AUDITOR.py.txt`. The first
peer attempt used merchant ordering where the replication bootstrap uses sorted
source IDs, producing a small finite-Monte-Carlo interval mismatch. That auditor
ordering was corrected; both logs are retained. No experimental output, policy,
reported interval, or acceptance gate was changed.

Five focused behavior tests exercise rule fallback and learned exceptions,
missing-label masking, exclusion of target images from inference, source-cluster
uncertainty, rejection of unbounded archive downloads, and exactly one decoder
dispatch after a public encoder decision. Commands and actual logs are preserved
in `evidence/TESTS.json`. They precede the repository's final formatting pass.
The natural peer independently audits the separate native owner continuation;
its receipt is `evidence/PEER_CONTROL.json`. That audit distinguishes a zero
feedback intervention from a reoptimized no-feedback baseline and does not
relabel the failed semantic-critic qualification as passed.

`evidence/PEER_ADMISSION.json` independently checks the subsequent 1,024-case
native admission study's statistics, 2,692 media paths, chronology, expiry and
generation-budget behavior, 51,200 accounted kernel executions, and charged
terminal moments. Its unchanged legacy-shaped ECE/coverage/declared-missing-OOD
predicates pass, while the additional incorrect-commit criterion fails at
3/424. A labeled posthoc matched-sunk-cost comparison also does not establish
an entropic-value improvement over terminal abstention. Low calibration error
therefore is not presented as risk optimality. The native study's source media,
models, owner traces, and full replay audit have their own evidence package;
this natural package contains the independent peer code and report.

## Recovery and reproduction

The repository base is `fb9281e4a7ccfc4034281ed6310adea7e50f4474`.
`requirements.txt` and `evidence/RUNTIME.json` record actual dependency versions,
thread configuration, binaries, and OCR checkpoint identity. Fresh-source
qualifications use LibriSpeech revision
`71cacbfb7e2354c4226d01e70d77d5fca3d04ba1` and SROIE revision
`bffe40c26759f3376ec2b3ae9031dbba54cd587c`; DAVIS source identity is documented
through the range and member evidence described above.

The content-addressed raw archive contains every new asset, completed development
run, qualification, replication, actual output, model selection record, executed
source snapshot, audit, and log. It also includes the old development inputs and
source dependencies actually used here. Equal-byte media may share an inode in
the working copy only after SHA and byte equality checks; all logical paths and
content identities remain in the archive index. No negative output is omitted.

One public 145,216,508-byte Whisper `model.bin` is explicitly external to avoid
duplicating that large frozen file. Its immutable URL, size, and SHA are in
`evidence/MODEL_RECOVERY.json`; tokenizer/config files and the OCR language model
are included. Raw answer/pixel/statistical audits do not require redownloading
Whisper. Neural regeneration does require that exact model and the recorded
runtime. Original manifests retain absolute paths. Relocating a replay therefore
requires an explicit path view or remapping; the archive is not described as an
automatic relocatable full neural replay.

The existing continuation restore helper verifies the archive by writing,
reopening, and hashing every logical file, with bounded temporary storage:

```bash
python experiments/multimodal_output_portfolio/continuation_20261027/natural/restore_evidence.py \
  --archive /absolute/path/ndu_natural_closure_v2_20261027.tar.gz \
  --destination /absolute/path/temporary-restore \
  --verify-discard --receipt /absolute/path/restore-receipt.json
```

Run the independent replication audit against restored assets and a path view
that resolves their recorded workspace:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m \
  experiments.multimodal_output_portfolio.closure_v2_20261027.natural.audit_replication \
  --assets /absolute/workspace/natural-v2-assets/document-replication \
  --experiment /absolute/workspace/natural-v2-runs/document-replication-001 \
  --first /absolute/workspace/natural-v2-runs/document-qualification-001 \
  --output /absolute/path/independent-replication-audit.json
```

Generation modules expose explicit `--assets`, checkpoint, and new output-directory
arguments. Reproduction must use a fresh directory and the authoritative executed
source snapshot for its run. Rerunning a frozen qualification cannot supply a
new independent statistical replicate. The completed records, original negative
gates, and one capped replication remain the evidentiary units.
