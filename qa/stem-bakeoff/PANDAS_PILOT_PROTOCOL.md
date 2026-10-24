# First unexposed pandas source/build pilot

Baseline: `56b5815a8ae811f6846e92dbbe46ca1a74d83f2f`.
The prior audit recorded pandas169, keras45 and spaCy10 as unused by the pinned
local study inventory. This is a bounded exposure statement, not a claim about
pretraining corpora. Metadata availability is not a label or successful execution.

## Outcome-independent pilot selection

Choose **BugsInPy pandas bug5** solely because it is the one pandas metadata
record already giving a full 40-character base revision. Fix its role as TRAIN
and build qualification before fetching or importing target source. It is never
a new holdout, and it is not selected by command outcomes or model performance.

- Metadata repository: `https://github.com/soarsmu/BugsInPy`.
- Metadata commit: `11c5f1eea954a42132cfd06bf257766a7963e0fd`.
- Target repository: `https://github.com/pandas-dev/pandas`.
- Base: `4f4282f8a7c1033fc3efe9f4eab5368a70ae5041`.
- Candidate: `0babe10f1f3f19bb6183b6fb4cc958583c6860c8`.

Pin metadata, full source commits/trees, dependency profile, interpreter and
build inputs before any benchmark action. Preserve original requirements and
setup commands. Exact metadata versions take precedence; necessary bootstrap
support must be declared from static build requirements. Use the available
CPython3.8.20 with the metadata's Python3.8.3 difference disclosed. An installed
modern pandas or extracted code fragments are not substitutes for the target.

## Actual source and runtime qualification

Acquire only the two fixed revisions in a fresh source store. Build the whole
source project, including its native extensions, in a new bounded runtime.
Do not mutate older experimental environments. Begin with serial builds and
one compiler job; never execute the upstream unrestricted `-j0` command. Keep
source packs below750MB and provision runtime/build storage conservatively
below2GB, checking disk and cgroup pressure before large allocations. A limit
failure remains evidence and does not turn into a missing zero-cost run.

Prefer independent builds for the two revisions. Any compiled artifact reuse
must prove identical complete native build inputs, ABI, compiler and dependency
identity; Python-only patch headers alone are not that proof. Bind generated
extensions to their source revision and retain their hashes. Import provenance
must resolve to the intended checkout and its actual generated extensions.

At this initial qualification stage, only acquisition, dependency installation,
build and import smoke checks are authorized by the protocol. Freeze prepared
primary actions and deterministic same-file comparators in a separate plan
before benchmark execution. Preserve original test bodies and command semantics;
do not silently delete build products with the old pure-Python runner's
`git clean -ffdx`, or replace missing extensions with an unrelated wheel.

## Outcomes and the subsequent learning study

Any later execution must pair each frozen action across clean source revisions
with matching test overlays and runtime, resource limits, logs and observed
test collection. Infrastructure errors, skips, no tests and timeouts stay unknown.
Do not infer a differential outcome from the supplied bug label. A successful
pilot is one TRAIN group, not169 executable groups or n128 support.

No new model fitting, Encoder extraction, calibration or heldout evaluation is
part of this pilot. Expand acquisition and execution only through a new frozen
candidate/role plan; report attempted and usable groups separately. Record all
wall/parent/child CPU where measured, failed attempts and unresolved dependency
or build requirements. Remote CI is excluded throughout.
