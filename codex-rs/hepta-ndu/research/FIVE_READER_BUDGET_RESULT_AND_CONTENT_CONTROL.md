# Fixed-dose result, failed projection qualification, and nonempty-content control

Date: 2026-10-14. PR #1697. Parent efe97de488622b14bab1d42bbf90d4c8249734a0.
This increment changes no existing trainer, model, threshold or serving owner.
The new read-only study was submitted without claiming execution at publication.
Local container, private Python and visible Python returned infrastructure
ClientError. No new local test pass or downloaded-artifact rehash is claimed.
The observations below were read from complete decoded hosted logs and final
job statuses, not inferred from a queued job or a PR description.

Current content-swap implementation is 7a94d9e5e6bd2f6c6e516405f115abe65428073f.
Run38493158981 / job115622846069 has now completed its required-test STEP and
all three external archive SHA checks successfully. Its saved-model comparison
is in progress. Individual test counts and the final model result are not yet
claimed from a completed log. This note changes documentation only.

## 1. Eight epochs change the proxy criterion but do not establish semantic learning

Fixed-budget implementation 00104aaf8eff351359a779ccc034cbbe6e4aa023,
run 38437516618 / job 115435273598 completed SUCCESS. All 312 focused test
invocations passed; 309 distinct test identities, zero skips. Three imported
NativeAdapterTests repeat in the pair suite. The 25 fit-audit tests passed.
This is not full-repository, Rust, target-device or prospective-merge acceptance.

All 120 planned free-generation rows completed. These reuse four TRAIN questions
under TWO conditions and four SELECT questions under FOUR conditions, across
five arms: (4*2 + 4*4)*5=120, not 120 independent tasks. Teacher-forced audit
used 14 TRAIN pairs and three SELECT pairs with available annotations; the
fourth SELECT target is missing. TEST families conv-43 and conv-47 remain excluded.

| Arm | TRAIN both conditional preferences positive | SELECT both positive | TRAIN/SELECT mean full-target support margin |
| --- | --- | --- | --- |
| Frozen | 0/14 | 0/3 | -1.105180 / -1.030146 |
| Aligned 2 epochs | 0/14 | 0/3 | -0.886006 / -0.778072 |
| Shuffled 2 epochs | 0/14 | 0/3 | -0.925939 / -0.810384 |
| Aligned 8 epochs | 14/14 | 3/3 | 5.368085 / 5.003146 |
| Shuffled 8 epochs | 14/14 | 3/3 | 4.967719 / 4.839901 |

The uncited-body diagnostic ALSO reaches 14/14 and 3/3 for both eight-epoch
models. This rules out the claim that this proxy remains unmet regardless of
optimization dose, and does not support blaming the entire earlier gap on the
citation suffix. These are length-normalized teacher-forced score comparisons,
NOT semantic accuracy, calibrated probabilities, or independently reviewed
sufficiency. The shuffled model meeting the same criterion shows that the
criterion does not establish correct evidence/answer pairing.

Both eight-epoch models emit prescribed refusal on all four empty TRAIN inputs
and all four empty SELECT inputs, but none of the nonempty inputs, including
support-removed inputs. This is consistent with an evidence-presence shortcut;
it does NOT prove every nonempty answer is wrong or every donor context is
insufficient. All five arms have zero registered exact-body matches. Aligned-8
has one syntactically valid citation on support-only TRAIN and one on SELECT;
syntax is not grounding. The first answer/refusal branches both choose the
intended tokens for only 1/14 TRAIN and 1/3 SELECT with aligned-8, and 0 for
shuffled-8. Pairwise score improvements do not ensure the actual greedy path.
No new independent semantic judgments or candidate adoption are made.

The two short fits each ran 28 actual optimizer updates /112 decoder forwards;
the two long fits each ran112 updates /448 forwards. In all:280 updates and
1,120 training decoder forwards, plus2,880 generation and510 audit forwards.
Loads, staging, tests and earlier runs are additional. The two actual short
example schedules are exact prefixes of their corresponding long schedules;
intermediate tensor equality was not established. All saved adapters reloaded
exactly and immutable-base checks passed. No matched-total-compute claim.

Artifact11838105827: GitHub reports5,424,838 bytes /518 files.
ZIP SHA256 ce5178bf4bea0d45d65f22765e29a835b7a99a4b3a4fd1dc4fa0d248a6d5c151.
Raw SHA256 f23a754463619360de226748f1c502a43339703adbb1b1c9284f3d08dd9fac92.
Plan SHA256 471bfaf3ef3af40ba9f0d9e4d546a1caacfdf25441c5e76df3cff8b9e9fed205.
The artifact was downloaded but local verification did not run due to the
infrastructure error; the new lane verifies the entire ZIP and every member.

## 2. Assistant projection: measured work reduction, failed saved-weight tolerance

Projection implementation efe97de488622b14bab1d42bbf90d4c8249734a0,
run38441421072 / job115448680122 completed FAILURE. Its332 focused test
invocations /329 distinct identities passed, including all20 projection tests.
Both real one-epoch fits completed14 updates /56 decoder forwards with the
same initialization, token census and exact own-checkpoint reload. The full
per-step loss comparison passed before the saved-adapter comparison failed.

The FIRST reported failing tensor had one failing element among2,304, absolute
difference2.5566841941326857e-6 against the original atol2e-6 /rtol2e-4 test.
This is not a count over all adapter tensors: the comparison stopped there.
We do not widen tolerances, suppress this element, label the run green, or
change full-logits-v1 as the default. Numerical shape-dependent rounding is a
plausible contributor, not an experimentally isolated explanation of the entire
trajectory. The new lane enumerates ALL saved tensors using the original gate.
It still emits projection_qualified=false and retains the old failure.

Observed vocabulary-output work, full versus assistant-only:
- projected positions:11,066 versus1,122;
- produced output bytes:2,175,664,128 versus220,594,176;
- largest returned logit tensor:108,724,224 versus11,010,048 bytes.
These are actual LM-head observations, not whole-process peaks or Transformer
activation memory. Whole-fit region wall times were55.478322651s versus
46.787175065s on this one fixed-order run; this is not an established general
speedup. Decoder context, backward costs, shared-cell serving and energy remain
separate. Optimization savings do not authorize an unqualified replacement.

Artifact11837123194: GitHub reports1,879,499 bytes /56 files.
ZIP SHA2564259beaea0c23cbd80d945b464b83ff23af5c1185d7c2fe469409c0043c6c38d.
No local rehash asserted. The read-only lane also binds its original plan/source.

## 3. New experiment: distinguish nonempty content, without another fitting run

Use the exact saved frozen/aligned2/shuffled2/aligned8/shuffled8 candidates from
the completed budget artifact. ZERO new optimizer updates. The current official
loader and strict adapter composition checks remain owners of all model loading.
No hidden fallback to a local arithmetic model or the unqualified projection.

For every admitted TRAIN/SELECT recipient choose one donor from the SAME
partition, a DIFFERENT source family, with the SAME number of sources and a
different exact annotated answer and source body. Choice is an identity hash,
not model output, score, length or outcome. No donor means an explicit retained
unavailable row. The question and options do not change when sources change.

Both contexts use the same local citation names S1,S2,... with original source
ID/position provenance retained outside the prompt. Source text and session
metadata stay verbatim. This stops citation-name matching from trivially solving
the comparison. Lengths, semantic topic and dates may still differ; this is not
an isolated word-content or equal-token intervention. Different donor answer is
not an independent proof that it is false, nor that donor evidence is insufficient.

Under each fixed recipient question q, score own answer a and donor answer b
under own nonempty sources E and donor nonempty sources D:

I = [l(a|q,E)-l(b|q,E)] - [l(a|q,D)-l(b|q,D)].

Evidence-independent answer preferences and additive context score offsets
cancel. Positive I is a content-sensitivity diagnostic, NOT a semantic correctness
or admission test. Annotation bodies are exact uncited post-generation diagnostic
targets, never revised training targets or model-answer edits. No adversarial
semantic negative label is fabricated from a cross-family donor.

Reuse the prior fixed free-generation recipients (four TRAIN/four SELECT),
including unavailable reference/support rows. Generate own-source, donor-source
and empty conditions; seal every arm's raw output before scoring target-bearing
likelihoods. Both nonempty branches have identical local citation IDs. The empty
condition remains truly empty. Only public request fields enter generate_exact.
Teacher-forced audit retains the full admitted recipient census and uses four
full-logits-v1 forwards per eligible comparison. No optimization is called.

Report raw output, refusal/format/exact-body diagnostics, individual directed
edges, recipient-family macro interactions, unavailable cases and all observed
work. Donor reuse induces dependence; no artificial sample multiplication or
confidence intervals are issued. State and disk bytes are checked at load/end.
An integrity failure remains an error, never a successful candidate.

## 4. Submitted verification and execution boundaries

New files reader_content_swap.py, reader_content_swap_trial.py and
 test_reader_content_swap.py contain27 new test definitions (15 controls,
5 interaction/readout,4 archive integrity,3 official tiny-model checks).
At publication they were submitted without a local passing claim. The subsequent
required-test step is successful as noted above; individual log counts await
completed-log inspection. The dedicated lane requires all inherited suites and
these tests before any original-model execution. It then downloads three fixed
archives, verifies every result member, loads previously saved adapters, and runs
the read-only experiment. It neither reruns eight-epoch training nor modifies
the earlier workflows.

The supplied archive code is never imported. Original pretrained models and
archived source/material copies stay outside the exported output tree. Current
source, exact commit, all test logs, outputs, tensor-drift inventory and failures
are retained. Missing FLOPs/energy remain unknown. The host is not a malicious
code sandbox; this is a bounded research task, not a production owner.

All prior evidence, five-experiment protocol, independent dual-signed Reader
gates, Group/NDU and multimodal scope remain. The budget result advances the
proxy-fitting question; correct semantic content use and actual task-quality
benefits still require stronger evidence. No main/CURRENT/model activation.
