# E1–E6 continuation: frozen diagnostic candidate and retained results

This directory records the November 18, 2026 continuation of the existing Cell
experiments. The new four-task panel produced **no task-coverage gain over the
single-call answer-SFT control**. A separate cold repeat reproduced all 60 node
answers, requests, model identities, token counts, and business decisions.
These are curated development observations, not independent learning
confirmation, new users, external teachers, or native-owner adoption.

## Exact candidates and review stack

| Draft PR | Commit | Change |
| --- | --- | --- |
| [#6686](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6686) | `546120c88d70ce41705f045a1f22929ab4ec4f90` | Bind E2 readout to the original task, input, answer, verifier parameters, and observed controls |
| [#6687](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6687) | `75227884493119fe861a102ca96481ab6bdda875` | Preserve E6 measured work and unknown costs when inference or verification fails |
| [#6688](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6688) | `791f3adbc4768cb17869725294e20578fb044be9` | Add four evaluation-only tasks from different repository functions |
| [#6689](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6689) | `fe0b7aaf40ed76cd6021afd428c5efc14a6f437a` | Isolate the diagnostic provider while retaining the original model and source gates |
| [#6690](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6690) | `8c60a4bb2dc183a859bc5ae4adee60bc0ba6c613` | Freeze the 60-call protocol and retain actual child exits and raw protocol output |
| [#6692](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6692) | `581c4c060836b6600ed1676894972a96321b292d` | Integrate the published adapter precision repair and explicitly select the new module root |
| [#6694](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6694) | `4d9fc82c1efff45f964d4efdc6155b350e01fd23` | Freeze the two actual Cell support imports and declare the cold repeat |

The stages are stacked on the existing #6672 experiment branch. The first
model run used `581c4c0`; the repeat used `4d9fc82`. Candidate `8c60a4b` made
zero model calls before the loader correction. The original retained model
directories and their manifests were not rewritten.

Both runs used Qwen2.5-Coder-1.5B-Instruct revision
`2e1fd397ee46e1388853d2af2c993145b0f1098a`, the same three previously trained
adapters, and the original tensor-after and runtime identity checks. Here
**F means final-answer SFT**, T means trajectory SFT, and C means controlled
correction SFT. F is not an untrained frozen-model baseline, and these adapters
are not three independent external teachers. They are the retained Run02
adapters, not the final updated E2 Run03 students.

The pool loader source hash is
`110b33222dc620ce5fb61b1e4ff9fb4b4e5f7bb03ee25a4c9c726e99f7476d3c`.
The repair allocates and promotes each adapter before copying its FP32
weights, avoiding an irreversible FP32-to-BF16-to-FP32 round trip. Original
model hash, tensor count, base identity, and cleanup checks remain active.

## Task and interaction scope

The four evaluation-only tasks use `normalize_machine`, `format_kib`,
`cargo_profile_dirname`, and `archive_format_for_path` from repository source
commit `d0070b6985f54bc2d72e4bf82153b9872e31eb52`. The original source files,
Git blob identities, prepared records, reference checks, and wrong-output
controls are retained under `../cell-diagnostic-panel-20261118/`.
The functions differ from the old A/B panel, but they still come from the same
project and were selected for development. The panel labels **c/d do not mean
native E6 C/D**. Training on this panel is disabled.

The eight arms were frozen before generation: FF, TT, CC, TF, CF,
TF without the answer message, TF without verifier feedback, and F with one
call. Every two-call arm still pays for the second call after an initial
success. All calls use the same ceilings of 4,096 input tokens, 384 output
tokens, and 2,048 relay bytes. Actual token costs differ across arms; the data
do not establish a matched-actual-cost advantage. Routes are fixed protocol
graphs, not a newly learned routing policy.

## Observed results

Each cell below is the number of successful tasks out of the same four tasks,
per run. Both runs give exactly the same table.

| Arm | First attempt | Last attempt | Selected attempt | Calls | Recovery 0→1 | Regression 1→0 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| F one call | 1/4 | 1/4 | 1/4 | 4 | — | — |
| FF | 1/4 | 0/4 | 1/4 | 8 | 0 | 1 |
| TT | 0/4 | 1/4 | 1/4 | 8 | 1 | 0 |
| CC | 0/4 | 0/4 | 0/4 | 8 | 0 | 0 |
| TF | 0/4 | 0/4 | 0/4 | 8 | 0 | 0 |
| CF | 0/4 | 1/4 | 1/4 | 8 | 1 | 0 |
| TF without answer | 0/4 | 0/4 | 0/4 | 8 | 0 | 0 |
| TF without feedback | 0/4 | 0/4 | 0/4 | 8 | 0 | 0 |

All successes occur on the same machine-alias task. No arm solves any of the
other three tasks. The selected result is the earliest successful attempt, or
the last attempt when none succeeds. Reporting only the selected score would
hide FF's successful first attempt becoming an unsuccessful second attempt.
TT and CF each recover on the task already solved by F alone; that recovery
does not add task coverage.

Per run, 33 of 60 generated responses fail the frozen literal/JSON format
contract. Of the 27 executed responses, four satisfy the original subject
and all wrong-output controls, 19 fail to reject all controls, and four fail
the original subject. `DIAGNOSTIC_RUN1_FAILURES.json` records the observed
categories and examples. These observations do not by themselves prove a
causal account of the model failures.

## Cold repeat and source-freeze correction

The first import audit found two actual first-party imports absent from the
initial provider inventory: `hepta_cells/__init__.py` and
`hepta_cells/semantic.py`. Their original bytes are preserved in the first
archive, but **they were not bound by that run's freeze**. The first freeze
and result have not been rewritten.

The repeat adds checks of the actual imported paths and hashes before
generation, on every request, and at provider closure. Its source deployment
differs in only `diagnostic_provider_v4.py`; the models, records, arms, caps,
and other source inventories are identical. This repairs the identified
support-source omission; it is not a claim that every possible dependency
or physical cost has been completely measured.

`DIAGNOSTIC_REPEAT_COMPARISON.json` reconciles all 60 nodes and 32 graphs.
Every request, answer, model identity, token count, and business decision
matches. The provider processes are distinct, both actual `Popen.wait`
results are zero, and neither run needed termination, killing, timeout, or
automatic retry. The four tasks had already been exposed before the repeat.
**The repeat adds zero independent samples.**

## Costs and exit evidence

| Quantity | Run 1, `581c4c0` | Run 2, `4d9fc82` | Combined |
| --- | ---: | ---: | ---: |
| Model calls | 60 | 60 | 120 |
| Verifier calls | 60 | 60 | 120 |
| Input tokens | 22,247 | 22,247 | 44,494 |
| Output tokens | 3,239 | 3,239 | 6,478 |
| Business executions | 27 | 27 | 54 |
| Format rejections | 33 | 33 | 66 |
| Owned elapsed seconds | 317.354 | 302.968 | 620.321 |
| Shared pool initialization seconds | 54.070 | 53.344 | 107.414 |

Owned elapsed/child CPU observations include waited helpers and descendants.
Pool initialization and model/verifier timings are nested scopes and must not
be added again to the encompassing total. Initialization is charged once per
pool, not once per node. Energy, GPU-active time, monetary cost, and some
system costs remain unknown; unknown values stay null. Full-system cost and
actual-cost matching remain unqualified.

## Retained originals and independent readout

The readout audits semantic receipt hashes and their exact task/input/answer/
verifier-parameter bindings; original-subject and wrong-output-control
observations; graph contracts and selected slots; pool and adapter identities;
all 60 node inventories; token accounting; source freezes; and actual child
exit receipts. It performs zero model or semantic-verifier calls.

The complete original archives are kept as ordered valid ZIP parts under
`raw/run-1/` and `raw/run-2/`. Each ZIP contains one `payload.bin`; concatenating
payloads in the order specified by `ARCHIVE_PARTS.json` reconstructs the exact
original gzip tar. The external `INDEX.json` records every member's original
path, size, hash, and binding. The publication checks the full reconstructed
archive hash, unique/safe member names, and every member against that index.
Run `python qualification/cell-joint-20261118-556e/verify_archives.py` from the
repository root to repeat this byte audit without model or verifier calls.
Optionally append `--write-archives /absolute/new-directory` to write the two
verified original gzip tars to a new directory; the helper does not extract
their members or overwrite an existing destination.

| Archive | Bytes | Members | SHA-256 |
| --- | ---: | ---: | --- |
| Run 1 | 655,242 | 647 | `4a94e9a761bf107ec56be309e96f6da7a34053dde1efd312c2829a8d0af458bb` |
| Run 2 | 672,949 | 653 | `4e447509104c39bcf7ca69e95f4ecde7e58fadb1b038c2a8752f169afbc97af4` |

The archives include raw requests, answers, verification results, intents,
step receipts, stdout/stderr, protocol records, source packages, deployment
records, original model/training manifests, and audit material. Model weights
are referenced by original revision and byte hashes instead of being copied.

## Relationship to the existing E2 and E4 runs

The existing E2 actual-update evidence is published in
[#6678](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6678).
It must retain its final primary and cold B failures, including 0/3 for all
three updated arms. The reference-trajectory arm used nine authored
supervised turns per round, while shadow and controlled used six correction
targets per round; these conditions are not information- or cost-matched.
The strengthened E2 reader reproduces the three historical reports exactly
while rejecting transplanted or forged semantic receipts.

The existing strong-control E4 evidence is separately published in
[#6693](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6693),
head `a6c32fa20295a0fe38aa69f72d9c5f94712caaf1`: 162 graphs and 306 model/verifier
calls. On old A, the selected learned-route, FF, and best-static scores are
all 5/6; every old-B route/control/ablation remains 0/3. Learned-route and FF
each have five first-attempt successes that become zero last-attempt
successes. The selected score alone conceals those regressions. These are
separate source/task protocols and cannot be pooled into a single joint
candidate qualification. Its 3,035-file original archive hash is
`7e0a67d8c4cdfadbebf195591bbe30cce2e6ed9b524c46c6011b0cadcb8f3a32`.
The published final readout hash is
`8599d61793f97da236afb53aab382eba9b0a072752705c053aca8264977c3a94`.
`EXISTING_E4_INSPECTION.json` is a separate compact inspection, not a byte copy
of that final readout; `EXISTING_E4_PUBLICATION.json` records the publication.

## Validation and remaining E1–E6 evidence

The exact `581c4c0` candidate passed its dedicated engineering CI: 208 tests.
The exact `4d9fc82` candidate passed both dedicated jobs: 208 tests each.
`CI_581C4C0.json` and `CI_4D9FC82.json` bind source commits, log hashes, and
job identities.
Earlier staged CI counts were 197, 201, and 207 as recorded in
`CI_OBSERVED.json`. These counts are engineering tests, not model-task scores.
The entire repository is not reported green: other repository checks
include a cargo-deny failure, pending jobs, and a retained earlier
runner-startup failure. No CI gate was bypassed.

Local validation also preserves the original incomplete sparse-checkout run
and its missing-fixture errors, followed by the targeted checks after the
exact original fixtures were restored. It is not relabeled as an initially
successful full suite. The numerical pool repair, receipt adversaries,
interrupted-cost cases, protocol cases, and final formatting evidence remain
in this directory.

| Experiment | What this continuation supports | Still absent |
| --- | --- | --- |
| E1 | Frozen evaluation protocol and retained negative results for existing SFT adapters | Independent future tasks; complete frozen/retrieval/answer/trajectory comparison with aligned information and cost |
| E2 | Actual-update evidence remains reproducible; strict receipt binding prevents fabricated recovery | Retained gains on independent tasks after real updated-student deviations |
| E3 | Explicit Cell identity and adapter-source accounting | Genuinely distinct authorized teachers and matched-compute complementarity |
| E4 | Actual two-step interactions, strong same-model controls, answer/feedback ablations, separate first/last/selected results | Independent-task collaboration gain and learned-routing necessity |
| E5 | No fabricated source/user increment | Deduplicated real sources and both fixed-total and fixed-per-source budget curves |
| E6 | Interrupted work/cost preservation; truthful separation from the native owner | Original-owner adoption, complete native C, fresh cold D, and full state/cost closure |

The native owner repair and Chain liveness work have separate exact source
identities and evidence. Their progress is not silently incorporated into
this Cell candidate. Engineering `ADOPTED`, process exit zero, or a passing
diagnostic task does not grant native-owner, FinalUse, reward, or settlement
qualification. No merge, production activation, or public-network readiness
claim is made by this evidence publication.
