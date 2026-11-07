# Real sources, candidate admission, and the remaining confirmation work

Status: **REAL_PILOT_TRAIN_AND_DEVELOPMENT_CANDIDATES_ACQUIRED; SCIENTIFIC_HOLD**.
This supplements the frozen `PROTOCOL.md`; it does not replace its six gates,
external owner registry, complete matrix, or statistical requirements.

## Actual acquisition

The rule selecting the first three lexicographically ordered official VizWiz
**train** image IDs was fixed before downloading annotations, without answer
filters. The original JPEGs, full original
annotation records, official annotation ZIP, source/license pages, range-request
journal, byte hashes, and resource receipt are retained. No model was executed.
The acquired IDs are `VizWiz_train_00000000.jpg` through `00000002.jpg`.

The acquisition consumed 6,219,434 HTTP body bytes across 17 requests, under a
25 MiB cap. Its inclusive recorded function cost was 0.854629217 CPU seconds,
76.700577838 wall seconds, and 189,202,432 bytes process peak RSS. Request costs
are nested, not additive. Startup, final writes, wire/header bytes, energy and
actual charges remain unknown. Three preliminary HEAD probes are a separate
partial-cost record; they are not hidden inside these acquisition totals.

A second prospective plan then fixed IDs `00000003` through `00000008` as six
**pilot train** records while preserving the first three development roles.
This extension reused the original annotation/license bytes and consumed
4,845,049 additional body bytes in 23 requests: **11,064,483 cumulative bytes**
under the same 25 MiB cap. Its separate inclusive function cost was 0.902228249
CPU seconds and 90.088900007 wall seconds; peak RSS was 185,065,472 bytes. Its
runtime-source hashes were fixed before requests. Neither acquisition ran models.
The final combined pool has six train and three development records, with no
confirmation allocation or independent-cluster claim.

The 11,298,421,598-byte image ZIP was never fully downloaded. ZIP64 metadata and
the selected members were read using exact HTTP 206 ranges under a stable
strong ETag. The complete image-archive SHA is unknown; each acquired image has
its own SHA and CRC check. The original annotation ZIP SHA is
`dbc32fc1e3f1b1039aea906030d569d6c238b4ddb2eea5e3453a6a565c829ec9`.

The initial run's plan predates runtime-source fields. Its unchanged source
files were captured immediately after execution and before further edits, in
`ACQUISITION_RUNTIME_PROVENANCE.json`; this is a post-run snapshot, not a native
execution attestation. Subsequent acquisition code pins runtime source bytes in
the plan before network access. No second acquisition was performed.

Candidate manifest SHA:
`d0f0f69385e56dc156ca1bfd1847509388eef6c6e60f0ef3e20ee80e18ce7350`.
Local exposure-history SHA:
`7f0ea4f10f1e679d534c905d9b4e3e7bc82d6eadd85c1cc287eca38cea325b8a`.
These pins bind a local acquisition; they do not impersonate an external owner.

Combined pilot candidate SHA:
`bfdc06b75f8c0f1fbefd2aa1c868dcf214dbc093554e21a067d470a7dfe1add0`.
Combined history SHA:
`7247a0d306aee50204e9c15cc5daa841191fd5ea8f520cbe8159474f04af39e5`.
The unchanged first-stage artifacts remain separately retained.

`ANNOTATION_EXPOSURE.json` also records that the full 20,523-record `train.json`
was parsed by acquisition, and that the ZIP also contains locally accessible
`val.json` and `test.json`. The selected-case history is not the complete
project/model exposure registry. An external owner must include this wider
annotation exposure; later samples from the same public train archive cannot
be advertised as secret, previously unavailable confirmation references.

## Observation and grouping contracts

`ndu_semantic_state.source_pool.admit_candidate_pool` validates the full supplied
history, including sources absent from a current selection. Source identity,
source group, episode group, derivative roots, original image bytes, and decoded
pixel identity cannot cross train/development/confirmation/retention partitions.
Re-encoding identical pixels cannot erase their earlier role. Inputs, reference,
provenance and exposure fields must match the separately pinned history.

For these nine candidates, upstream image IDs establish a conservative
derivative root. Photographer/session grouping is unavailable. Therefore the
reported **independent cluster count is null**, even though there are nine
different source image IDs. Pretraining exposure remains unknown. All nine are
project train/development material and cannot be promoted to confirmation.

`load_candidate_public_case(root, candidate)` preserves the controller interface:
only `text` and read-only `image_rgb`. Owner-side source/episode IDs and roles
never enter the online actor. `evaluator_public_view(public, delivered)` similarly
provides only current public input and current delivered output to learned
critics/evaluators; targets, family labels, split, source metadata and future
outcomes are rejected. This is a structural API boundary; native workers still
need real filesystem/process access isolation.

`score_vizwiz_reference` is a separate **deterministic reference grader**, not an
evaluation model. It applies ten-choose-nine human consensus to current text
using explicitly named Unicode casefold/whitespace matching. It is not official
VQA normalization, image-quality assessment, or independent domain certification.
The original references remain outside the actor and learned-evaluator views.
Actual grader invocations, including failures, require an external meter and
binding to the current terminal artifact; fixture scores are not real outcomes.

The original complete `materials.validate_materials` gate is unchanged. Candidate
integrity always returns scientific HOLD and cannot manufacture five family
labels, an old-capability panel, runnable models or native-owner evidence.

## Source choices and what their annotations can establish

| Source | Usable existing evidence | Limits and next action |
|---|---|---|
| [VizWiz official dataset](https://vizwiz.org/tasks-and-datasets/vqa/) | Natural blind-user photos/questions, ten external human answers; CC BY 4.0. Nine upstream train records acquired, allocated six pilot train / three development. | Can support a prospectively fixed text-answer endpoint. It does not rate generated image quality, prove five mechanism classes, or establish independent session groups. April 2026 server retirement/public test release prevents treating its public test labels as secret confirmation. |
| [Natural Questions official data](https://ai.google.com/research/NaturalQuestions/download) and [original paper](https://aclanthology.org/Q19-1026/) | Actual search queries with externally annotated textual answers; CC BY-SA 3.0. | Candidate text-sufficient endpoint. Group queries by canonical source document and derivatives before allocation. Not acquired. Support a real text-only input rather than inventing a placeholder image. |
| [RealEdit provider card](https://huggingface.co/datasets/peter-sushko/RealEdit/blob/76928c1fa1d3f09f9a5e4b4fd2ea75ed1f9903d6/README.md) | Original user `title`/`selftext` and human edits from Reddit; provider declares CC BY 4.0. | Its `instruction` is explicitly LLM-generated and cannot stand in for an original user request. Retain post-level grouping, raw provenance, target rights and link availability. Not acquired or family-qualified. |
| [GIER project](https://sites.google.com/view/gierdataset/home) | Real editing requests plus operation/mask annotations and additional crowd/expert language. | Separate original requests from augmented requests. Verify data reuse terms and upstream groups before acquisition; code licensing alone is insufficient. No family qualification asserted. |

## Prospective interventions needed for the complete study

Family assignment is a task/rubric registration before evaluating candidate
controllers. It is not a label inferred from whichever D−A result improves.
Keep unsuccessful/ambiguous cases and all acquisition, tuning and evaluation
attempts in the research ledger. A shared source reused for several interventions
remains one source/episode cluster, not several independent tasks.

| Intended family | Prospective registration and intervention | Existing human labels versus external work |
|---|---|---|
| Text sufficient | Register original textual request, supplied textual context and textual endpoint. Independently assess that context suffices; charge any unused image action. | NQ answer annotations can provide an external text endpoint. Study-specific source allocation and suitability still need owner registration; an optional-image input path is needed. |
| Complementary | Register original photo/question, endpoint and image-hidden/text-hidden diagnostic conditions before controller outcomes. Diagnostics cannot inform the deployed controller or confirmation selection. | VizWiz human answers support answer scoring now. Independent rubric review must establish relevant image/text dependence and any image-output obligation. |
| Selective refinement | Freeze an actual incoming multi-output draft and independently rate which output is deficient before running any candidate arm. Freeze improvement and non-regression rubrics separately. | Existing editing pairs provide request/target evidence, not a rating of this study's incoming text/image draft. Requires external blind assessment or actual owner workflow records. |
| Preparation before gain | Register real request, allowed preparation sequence, intermediate delivery checkpoints and final endpoint. Evaluate intermediate and final outputs blind to arm using the same rubric. | Grounded editing operation/mask data can help specify actions, but does not prove zero immediate gain or later benefit. Those claims require independently scored registered checkpoints. |
| Worthwhile stopping | Freeze task utility, action-cost conversion, failure penalty and minimum useful marginal benefit. Compare complete continuation policies; do not reveal future outcomes to actors or critics. | A VQA `unanswerable` label is not a stopping-utility verdict. Utility/cost values require the deployment owner; actual terminal outputs require external scoring. |
| Retention | Name incumbent abilities and independent source groups, freeze validation/confirmation partitions and subgroup non-inferiority margins before training. | Public human labels can score appropriate old tasks, but cannot establish which incumbent abilities must be retained or choose margins. Requires the owner’s capability contract and baseline receipts. |

The owner must then externally freeze source allocations and the full historical
registry; domain evaluators must approve rubrics and blind scoring; native owners
must seal runtime observation permissions and reconcile attempts. Train/tune
Light/NDU/fixed/VOI/MPC only on registered train/development. Sample size follows
the selected effect, variance and multiplicity policy, not these nine examples
or the protocol's minimum-cluster floor. Execute every A/B/C/D cell and comparator
in frozen and joint, preserve failures and all four factorial contrasts, and
retain independent training-fit identities separately from episode seeds.

## Reproduction

Acquisition is explicit and capped: with `PYTHONPATH=scripts`, run
`python -m ndu_semantic_state.acquire_vizwiz --output /ABS/NEW/EMPTY/PATH`.
It creates a local candidate history and never starts training. Re-admission
must receive the history SHA from the separately retained acquisition record,
not treat a pin supplied by an incoming candidate manifest as owner authority.

The six-record extension is
`python -m ndu_semantic_state.extend_vizwiz --previous /ABS/FIRST/BUNDLE --output
/ABS/NEW/PILOT/BUNDLE`. Its plan precedes image retrieval, reuses existing source
bytes, includes original development history, and shares the first run's byte
cap. Failed attempts retain their read bytes and resource records; a failed
extension must not be rerun with a reset ledger.

Run `python -m unittest ndu_semantic_state.test_source_pool
ndu_semantic_state.test_acquire_vizwiz ndu_semantic_state.test_materials -v`
with `PYTHONPATH=scripts`. The 31 tests include 13 new boundary cases and 18
existing material-admission cases; all use disclosed fixtures and no network.
