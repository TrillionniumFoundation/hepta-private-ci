# P0--P5 research execution evidence, 2026-11-10

This directory is an index of **executed work and its limits**, not an admission
certificate for the whole HCSN architecture. Read [CURRENT](../../CURRENT.md)
for the current scientific interpretation, [STATUS.json](STATUS.json) for
separate gates, [COSTS.json](COSTS.json) for accounting scopes, and
[assets.json](assets.json) for large source/model/log archives. The top-level
[MANIFEST.json](MANIFEST.json) binds every curated local evidence file.

No historical source, original failed attempt or old test record is replaced.
No merge or main update is part of this execution. The repository is public.
Large archives are attached to an **unpublished draft release**: authenticated
repository access is required. Sixteen assets have complete authenticated
byte-readback and anonymous-access receipts, including the seven completed
parent/C1 chains. The official raw-data ZIP and eventual original full fresh42
archive have separate unfinished archival work. See the exact states in assets.json.
The [asset reconciliation](publication/draft-asset-reconciliation-v1/SUMMARY.json)
preserves every attempted transfer: the official-data attachment is still a
`starter` with null server digest and failed authenticated download. Its
declared size is not verified uploaded data; the exact source file is retained.

The [earlier assembly review](review/curation-assembly-v1-failed.json) detected
a stale working index while these files were still being collected. Its
[original working manifest](review/curation-working-manifest-v1.json) is retained
as historical input, not used as the current manifest. The current top-level
manifest must be verified again after any evidence change.

## Claim-to-source map

| Claim | Source, execution and independent check |
| --- | --- |
| The missing original evidence was recovered exactly | [recovery verification](recovery-verification.json); original localization-v2 and math-closure manifests remain in their original directories |
| Definitions, drift signs and repeated readout are explicit | [model](../../MODEL.md), [semantic contract](../../semantic_contract.json), [targeted test log](p0/targeted-tests.log), [independent review](review/independent-review-v2.md) |
| 92 local regression tests pass | [raw qualification report](local-qualification/qualification.json), [raw log](local-qualification/qualification.log), [exact tested source ZIP](local-qualification/tested-source.zip) |
| Four original numerical budgets pass without relaxed limits | [budget report](local-qualification/error-budget.json), [raw log](local-qualification/error-budget.log), same source capsule |
| The two local runners bind the same 42 files | [source-equivalence receipt](local-qualification/source-equivalence.json), [capsule receipt](local-qualification/source-capsule-receipt.json) |
| Actual posterior, learned-physics and finite-schedule limits | [P1 summary](p1/summary.json), [costs](p1/costs.json), full P1 draft asset and its member manifest |
| P1 provenance independently checks out | [v3 review](review/p1-provenance-v3.md), [checks](review/p1-provenance-v3.json), [review program](review/review_p1_provenance_v3.py) |
| Fresh42 trace capacity cannot cover its full training trajectory | [exact v8 source audit](review/v8-recorder-scope-v1/RESULT.json), [scope explanation](review/v8-recorder-scope-v1/REVIEW.md); theoretical retention is at most 1.2243% at thirty epochs before the byte cap, not an observed retained count |
| Width-16 actual-posterior audit has scoped finite passes and two pressure failures | [scope and source index](p1/width16-v6/INDEX.md), [original summary](p1/width16-v6/summary.json), [original small-file copy verification](p1/width16-v6-copy-receipt.json); full traces/models remain in the bound draft ZIP |
| Raw-output full-data roster completed 36 attempts, only 2 adequate | [campaign summary](p2/raw36-summary.json), six raw arm archives in assets.json |
| All 36 saved runs were independently verified | [audit summary](review/raw36-summary.json), [exact audit archive identity](review/raw36-archive.json), [review program](review/review_campaign_raw36.py) |
| One first fit reproduced before the full independent audit | [first-fit report](review/first-fit-reproduction.json), [review program](review/review_first_fit.py); this overlaps the 36-fit audit and is not an additional fit |
| Frozen-head output domains have confidence limits | [analysis](review/frozen-head-domain.md), [raw certificates](review/frozen-head-domain.json), [actual head weights](review/actual-frozen-heads.json), [checkpoint identity check](review/head-identity.json) |
| CfC is bounded; the common adapter is an effective learned readout | [corrective follow-up](review/interface-microbatch-v1.md), [source hashes](review/interface-microbatch-v1.json) |
| Historical ten common-core/cache/microbatch behavior tests pass | [exact source capsule](p2/core-tests-source.zip), [receipt](p2/core-tests-receipt.json), [test stderr](p2/core-tests.stderr) |
| Current thirteen core tests pass on bound v8-equivalent source | [tested source](p2/core-v8-tests-source.zip), [source-before/after receipt](p2/core-v8-tests-receipt.json), [raw stderr](p2/core-v8-tests.stderr) |
| Five of six cores pass the adapter pilot's training-only diagnostic | [campaign](p2/adapter-pilot-result.json), [plan](p2/adapter-pilot-plan.json), full cloud diagnostics archive |
| Raw-spike PLIF does not pass after 1,024 steps and eight configurations | [1,024-step report](p2/plif-1024-result.json), [grid summary](p2/plif-grid-summary.json), [declared grid](p2/plif-grid-plan.json); timeout and partial model retained |
| Two analog PLIF readouts pass with a larger declared diagnostic budget | [complete diagnostics/source/checkpoint ZIP](p2/plif-analog-diagnostics.zip), [1,024-step roster](p2/plif-analog-1024-result.json); spike trace selected from training-only diagnostics |
| PLIF replay and CPU attention dispatch are independently checked | [PLIF review](review/plif-analog-review-v1.md), [attention profile](review/attention-cpu-path-v1.md), [independent outputs](review/plif-attention-independent-outputs-v1.zip), [75-member union map](review/plif-attention-union-v1.json), [union verification](review/plif-attention-union-v1-RECEIPT.json) |
| The actual native attention host also uses CPU flash SDPA forward/backward | [native worker report](review/native-attention-path-v1/worker-result.json), [complete process/cost receipt](review/native-attention-path-v1/RESULT.json), [exact profiler source](review/native-attention-path-v1/inspect_native_attention_v1.py); actual Xeon AVX2/FP64/causal mask, no optimizer step or comparative GPU/energy claim |
| HCSN width-16 cold/warm micro1 cost was measured | [probe report](p2/hcsn-micro1-cost.json), [outer process](p2/hcsn-micro1-process.json), full cloud diagnostics archive |
| Native effective-batch-32 micro4/8 costs were measured | [original controller](p2/native-cost-originals-v1/hcsn-effective32-cost-v6/RESULT.json), [original micro4 result](p2/native-cost-originals-v1/hcsn-effective32-cost-v6/micro4/RESULT.json), [original micro8 result](p2/native-cost-originals-v1/hcsn-effective32-cost-v6/micro8/RESULT.json), [earlier derived view](p2/hcsn-effective32-derived-summary.json); recovered raw hashes and shared fields agree |
| Fresh42 was dispatched, final results remain unobserved | [actual v8 source](p2/training-source-v8.zip), [plan](p2/campaign-v2-plan.json), [original native launch receipt](p2/campaign-v2-native-launch.json) |
| Exact cap-continuation implementation is verified; actual seven-fit C1 completed | [original 11-test package](p2/continuation-validation.zip), [actual C1 delivery source](p2/continuation-source-c1.zip), [combined 24-test receipt](p2/continuation-delivery-tests.json), [actual controller RESULT](p2/native-c1-completed-v1/RESULT.json), [independent seven-chain audit](review/baseline36-c1-native-v1/v2/output/SUMMARY.json) |
| Original native cost failures and effective-batch probes have recovered bytes | [recovery index](p2/native-cost-originals-v1/RECOVERY_INDEX.json), [copy proposal](p2/native-cost-originals-v1/COPY_PROPOSAL.json), [final byte-readback verification](p2/native-cost-originals-final-readback.json); one checkpoint is explicitly restored by matching content hashes |
| The current baseline segment completed without restarting original HCSN jobs | [complete native stdout snapshot](p2/native-recovery-v2/native-status-query-stdout.json), [C1 complete summary](p2/native-c1-completed-v1/SUMMARY.json), [independent audit](review/baseline36-c1-native-v1/v2/output/SUMMARY.json); confirmed adequacy is 33/36 after C1, with three retained memorization failures |
| Original strict-clock failures and their independent supplement are preserved | [failed v1](review/baseline36-c1-native-v1/v1/output/SUMMARY.json), [passed v2](review/baseline36-c1-native-v1/v2/output/SUMMARY.json), [all original small files and excluded large identities](review/baseline36-c1-native-v1/COPY_LIST.json), [six-core development quality/cost table](review/baseline36-c1-native-v1/v2/output/CORE_TABLE.json); no HCSN final checkpoint was read |
| Six original HCSN fits remain in progress at the 18:01 UTC observation | [latest exact progress record](p2/native-hcsn-progress-1801-v1.json), [17:44 record](p2/native-hcsn-progress-1744-v1.json), [17:20 record](p2/native-hcsn-progress-1720-v1.json); all memorization diagnostics passed and 36--37 epochs completed; no final-result claim |
| The seven C1 parent/continuation chains are archived exactly | [252-member archive receipt](p2/native-c1-completed-v1/ARCHIVE-RECEIPT.json), [complete authenticated draft readback](p2/native-c1-completed-v1/DRAFT-UPLOAD-RESULT.json), [small-file handoff](p2/native-c1-handoff-v1.zip); archive verification is separate from scientific review |
| A prospective continuation clock defect is fixed without rewriting C1 | [independent draft PR receipt](publication/continuation-single-clock-pr.json), [red/green validation and exact source](p2/continuation-single-clock-v1/SUMMARY.json); twelve tests pass, no native training uses this changed source |
| C2 recovery feasibility is prepared without launching another training phase | [v2 feasibility and limits](p2/c2-feasibility-v2/FEASIBILITY.md), [proposed plan](p2/c2-feasibility-v2/PROPOSED-C2-PLAN.json), [21-test receipt](p2/c2-feasibility-v2/validation/RESULT.json), [v2 capsule](p2/c2-feasibility-v2.zip); [v1 and its failed fixture](p2/c2-feasibility-v1.zip) and [independent counterexamples](review/clock-c2-independent-v1/COUNTEREXAMPLES.json) remain intact |
| Prospective clock repair and historical adapter were independently inspected | [independent review](review/clock-c2-independent-v1/REVIEW.md), [findings and exact input hashes](review/clock-c2-independent-v1/RESULT.json), [full source and counterexample package](review/clock-c2-independent-review-v1.zip); this static review does not claim native C1 execution |
| C2 v2 closes the three independently constructed guard counterexamples | [read-only closure review](review/c2-v2-independent-closure-v1/REVIEW.md), [source and test-receipt binding](review/c2-v2-independent-closure-v1/RESULT.json); native fit eligibility remains untested |
| Native continuation controller handles actual budgets and failures | [v3 package](p2/continuation-controller-v3-validation.zip), [nine-test receipt](p2/continuation-controller-v3-tests.json), [unsubmitted dispatch intent](p2/continuation-native-dispatch-intent-v3.json); original v2 package is retained |
| Independent final-review tooling is prepared | [frozen reviewer v2](review/fresh42-reviewer-v2.zip), [23-test/entrypoint validation](review/fresh42-reviewer-v2-validation.json), [phase-chain protocol](review/fresh42-c1-phase-chain.md); this is preparation, not a completed fresh42 audit |
| Finite fixed/learned/QVI boundary fixture passed | [oracle report](p3/qvi-oracle.json), [three-test log](p3/qvi-tests.log), [exact QVI/control source](p3-p4-source.zip) |
| Non-diffusion controls were generated and checked | [generated data](p4/generated-suite.zip), [three-test log](p4/generator-tests.log), same QVI/control source capsule |
| Official data were recovered exactly | [download receipt](runtime/official-data-download.json), [preparation receipt](runtime/official-data-prepare.json), [484-episode manifest](runtime/prepared-data-manifest.json), [frontend](runtime/prepared-frontend.json) |
| Publication and hosted CI are separately observed | [earlier P2 PRs](publication/p2-prs.json), [four new exact-tree draft PRs](publication/api-source-prs-v1.json), [17:37 UTC CI observation](publication/ci-observation-1737.json); queued and running jobs are not passes |
| Hosted declared CPU fixtures passed | [complete 14-file job artifact](publication/hosted-science-42827955616-1.zip), [source/tested-tree identity](publication/hosted-science-identity.json), [summary](publication/hosted-science-summary.json), [job metadata](publication/hosted-science-42827955616-metadata.json) |

The top-level manifest treats embedded archive manifests as opaque retained
files. Do not feed `p1/archive-manifest.json` or the cloud archive's member
manifest directly to the repository integrity command: their paths refer to
members of the corresponding downloaded archive, not to files in this folder.

## Exact source identities

The numerical regression capsule SHA256 is
`0f8f62837b72a3530f6a652f7c25b778a7459bad9738539339ae9782a2e0ccdf`.
It includes the 42 files named in both numerical runner reports and a capsule
manifest. One later documentation-only addition to TRAINING_DOMAIN.md was
reversed to reconstruct the original bytes; the original receipt's hash and
length match exactly. This reconstruction is explicitly recorded. No changed
numerical code is substituted for a tested file.

The canonical P2 ten-test capsule SHA256 is
`efb039b23888fde7814d0982b90d494ea6c07e3bc60e0de939c1da584f821472`.
It was captured immediately after the owner-frozen test run; there was no
automated pre-run digest for that direct invocation. All seven non-import
Python ASTs match the independently tested immutable v6 source. Formatting and
import cleanup are recorded, not silently credited to historical execution.

The actual v6 pilot/probe capsule SHA256 is
`3c9562e560208f6a291846d79431f5d4e0718d1c695dd98c88c4cbf5dedc9fb5`.
The cloud diagnostics archive retains its source ZIP, four completed diagnostic
run directories, all model checkpoints and logits, raw update/process logs,
configuration, data identity and standalone diagnostic drivers. The eight-grid
timeout is retained as an incomplete trial, not removed from the roster.

The full P1 archive SHA256 is
`a1a32db092bce32db2d5e75804cbca316d4bab02080cc57ace5f6490390c0b79`.
It has 189 members, including its 188-file manifest, exact per-run sources,
checkpoint/tensor identities, actual gap schedules, 80-digit reference results,
raw failures and a separately recorded resume. Source snapshots predate some
integration formatting; they are the tested source for those claims.

The raw-output campaign source archive SHA256 is
`3a398c4d4e771777af558b4484ef72063177d8fbdc7b8386b4d2634f5f7cad45`.
Its unchanged run-source-v1 and original checkpoint-selection rule remain part
of the six raw arm archives. New strict-best checkpoint selection never changes
what the old run selected.

The actual fresh42 v8 source ZIP SHA256 is
`288283cae2b2cf4e7b68432e040e643a5e1b00a7de961fc848dd5cf20eb46102`;
the canonical thirteen-test ZIP is
`b0080da54969520f68317aad2e6a79a3a93c6aa2f84c8b37bbe6fc547cfea03b`.
The receipt verifies inherited Python AST equivalence and unchanged tested
source; the original v8 bytes remain separately archived.

The C1 delivery ZIP SHA256 is
`f4b473aa4f373c1622bbdac90d61e33c64f0e9642b6c0506e7fec5b8885a3946`.
It preserves all 35 inherited v8 files exactly and adds three continuation
files. Its 24-test delivery run overlaps the earlier 13 core and 11 continuation
tests; execution costs remain separate, while test counts are not inflated as
independent scientific evidence. The Attention single test originally passed,
but its wrapper misparsed singular `test`; both the failed wrapper receipt and
the separate read-only reconciliation remain in the original validation ZIP.

The new PLIF/Attention output ZIP and existing PLIF input ZIP together reproduce
all 75 uncompressed members of the original combined package byte-for-byte.
The [union verifier](review/verify_plif_attention_union_v1.py) can check those
two retained packages without the original combined ZIP. This does not claim
that the original 729,786-byte ZIP was re-uploaded. The other 31 full-shape
Attention episodes remain explicit dependencies on the complete prepared-data
reconstruction chain, with exact input hashes retained in the output package.

## Reproduce local mechanics

Use a fresh output path for every invocation. These commands are examples of
re-running the same entry points, not claims that another platform will have
identical wall time. Extract the appropriate source capsule into a clean
working directory first. Use the exact Python/Torch/NumPy/mpmath versions in
the retained runtime receipt when reproducing a numerical claim.

```sh
python -m qualification.hcsn_differentiable.run_qualification \
  --threads 1 --output /tmp/hcsn-new-qualification.json
python -m qualification.hcsn_differentiable.error_budget \
  --output /tmp/hcsn-new-error-budget.json
python -m unittest discover -s qualification/hcsn_qvi/tests -v
python -m qualification.hcsn_qvi.run_oracle \
  --output /tmp/hcsn-new-qvi-oracle.json
python -m unittest qualification.hcsn_memory_controls.test_controls -v
```

The core behavior tests additionally need the pinned ncps and SpikingJelly
packages and the official S4 checkout at commit
`e757cef57d89e448c413de7325ed5601aceaac13`. The runtime archive includes the
installed lock, pip reports, import checks, exact S4 file hashes and setup
logs. It does not supply training credit.

```sh
HCSN_S4_REPO=/absolute/path/to/s4 \
  python proposals/localization-v3/test_cores.py
HCSN_S4_REPO=/absolute/path/to/s4 \
  python -m unittest discover -s proposals/localization-v3 -p 'test_*.py' -v
```

Read each raw campaign plan before replaying training. Plans bind effective
batch size, seeds, learning-rate roster, source and data manifests, epoch,
wall/memory limits and the common frozen tensors. Absolute paths identify the
original host. Relocate input/output paths explicitly for a new execution and
retain that new plan; do not edit the archived original. The training diagnostic
resets before main training. Checkpoints/logits and process journals are part
of the evidence, not optional summaries.

Read the actual outer wall ceiling as well as the plan's nominal ceiling.
The original fresh42 controller uses `min(14400, 15000 - dispatch_elapsed)`.
C1 inherits that actual ceiling and subtracts the parent's complete process
wall time. It is a separately declared extension after observed epoch caps,
with no new seed, learning rate or diagnostic, but with added optimization and
calendar time. Seven eligible continuations completed at 16:56:17 UTC, each
reporting the declared adequacy condition; independent real-chain review
subsequently verified all seven chains with a separately recorded clock
supplement. The failed first review and original records remain intact.
The original native jobs and
uncertain upload/publication requests must be reconciled before any retry.

P1 continuation is reproduced from its archived posterior, physical parameters,
full operator configuration and actual gap list. The independent finite oracle
disables future observations. Every scaled error is
`abs(error)/max(1,abs(reference))`; below unit reference it constrains absolute
error. The 128-cell and 256-cell trained candidates have different posteriors
and are not a same-posterior grid-convergence pair.

## Verify evidence bytes and links

From the repository root, after checking out this evidence commit:

```sh
python -m qualification.hcsn_differentiable.evidence_chain \
  --manifest qualification/hcsn_differentiable/evidence/p0p5-20261110/MANIFEST.json \
  --manifest qualification/hcsn_differentiable/evidence/localization-v2-20261108/MANIFEST.json \
  --manifest qualification/hcsn_differentiable/evidence/math-closure-20261108/MANIFEST.json \
  --markdown qualification/hcsn_differentiable/CURRENT.md \
  --markdown qualification/hcsn_differentiable/evidence/p0p5-20261110/README.md \
  --markdown qualification/hcsn_differentiable/evidence/p0p5-20261110/p1/width16-v6/INDEX.md \
  --markdown proposals/localization-v3/README.md \
  --output /tmp/hcsn-new-evidence-integrity.json
```

This validates retained bytes, safe ZIP members and simple local links. It is
not an independent truth oracle or scientific-admission decision. The exact
source/head/tree of hosted CI is recorded by the workflow itself; a source
branch and a tested PR merge tree need not be identical.

Hosted science run `42827955616`, attempt 1, passed 92 tests, the four original
numerical fixtures, historical evidence checks, and the QVI/control tests. Its
source head `bad0eb639737c5b15a6e2df34cbd682c831e9b9e` and tested merge commit
`ae2e403e7411d10a4d29368a62a51454b858c8d7` have the same tree
`0fd8f2f35e190442025005ca17a4662af522a491`. The downloaded artifact matches
GitHub's SHA256 `54d359c2087e2f7a5d3308267b16a3d6da22ac037efa3a621042e36066c2fab4`.
This earlier hosted run does not cover the later evidence assembly, v3 temporal
core tests or continuation code. Required repository checks remain pending.

## Data, cost and remaining research boundary

The dataset is the official [UCI Localization Data for Person Activity](https://archive.ics.uci.edu/dataset/196/localization+data+for+person+activity),
Vidulin, Lustrek, Kaluza, Piltaver and Krivec (2010),
[DOI 10.24432/C57G8X](https://doi.org/10.24432/C57G8X), licensed CC BY 4.0.
The exact official ZIP SHA256 is
`6660124b4d1fd98963c56a6804bbb0ca0c5ee12edc9b772c8a867148af20d0da`.
Preparation reproduced manifest SHA256
`0eb233da8d0b766c35356ba450d0572f1e6a87a47f1d8a17cd32c2ae6f25a1cb`.
Historical E metadata exposure remains disclosed; no E training or scoring is
credited in the current development study.

Costs distinguish campaign elapsed time, summed attempt elapsed time and CPU
time. These overlapping scopes must not be added. Cache construction, numerical
qualification, tuning diagnostics, failed configurations, interrupted jobs,
runtime setup, independent review and archival transport are separately named.
Unknown total historical cost, system energy, currency charges and VRAM are
null with reasons. A CPU process does not measure zero GPU memory or energy.
The original native uncached/cached probes and failed full-batch probe now
have recovered individual receipts and an explicit controller/case cost row.
The source-v3 batch32 allocation failure is exit 2, not an OS-kill claim; its
complete child wall is 52.017043 seconds. Original cloud v8, canonical v8 and
native v8 preflight test executions are separate cost rows, not extra
independent scientific coverage.

The finite QVI fixture is not a continuum free-boundary proof. The symbolic
controls are generated, not trained. The tiny-gap infinite-repeat pressure
failure is not silently exchanged for a passing finite sequence. The current
body of evidence does not yet establish HCSN superiority, a fully qualified
trainable-physics domain, real multimodal benefit, GPU efficiency or production
adoption. Each gate in STATUS.json must be changed only with its own evidence.
