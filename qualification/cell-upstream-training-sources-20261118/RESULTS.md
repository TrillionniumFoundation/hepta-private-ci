# Four real upstream repair sources for E1/E2/E5

Four newly selected upstream maintenance projects now have exact licensed code,
original regression tests and an actually reproduced before/after behavior change.
This closes the missing-material step for a prospective four-project training pool.
It does not establish a learning gain, independent users, future-task generalization
or native adoption. No model inference or training was run in this intake.

| Source | Original pull request | Original test cases per revision | Before | After |
| --- | --- | ---: | --- | --- |
| python-attrs/attrs | [1593](https://github.com/python-attrs/attrs/pull/1593) | 5 | 4 pass / 1 fail | 5 pass |
| Textualize/rich | [4006](https://github.com/Textualize/rich/pull/4006) | 24 | 14 pass / 10 fail | 24 pass |
| tox-dev/platformdirs | [721](https://github.com/tox-dev/platformdirs/pull/721) | 29 | 28 pass / 1 fail | 29 pass |
| python-humanize/humanize | [479](https://github.com/python-humanize/humanize/pull/479) | 56 | 53 pass / 3 fail | 56 pass |

The four old revisions produce 15 failures; the four corrected revisions pass
all 114 unchanged selected test cases. There are 228 actual case executions in
eight sequential owned test processes. No collection errors, outer process
timeouts, automatic retry or discarded source occurred. Rich's ten failures
include eight measured 3-second case timeouts and two incorrect results. Each
after run uses the identical timeout. Full original parameter sets are retained,
not only the failing examples.

## Source and execution identity

The parent coordinator named all four projects before this acquisition.
The selection rule and observed skips were frozen in commit
`04eea36b2ffe52a9e5105d0701880a0dedca9717`. Exact public Git blobs and
MIT notices were acquired by source
`5e78427a7e0bf2623177c10ab1ad9ab03932b80b`.
The eight native runs used
`b8568658762bb3a54c94253811d563b0f39dac3e`.
The material loader and growth schedules use
`c80a4cfdb49a49ed72cbdae18c0e4de68883c1d0`.
Evidence commits do not relabel these execution identities.

`SOURCES.json` pins each repository and organization ID, original public
author account, original creation/merge timestamps, parent/fix commit, every
selected package/test/license file, Git blob SHA1 and SHA256. The acquisition
contains 83 distinct Git blobs and 1,115,549 unique downloaded bytes. Four
repository/organization identities and four repair lineages are available.
This does not authenticate four human users or establish statistical independence.
The authenticated-user count is still **0**. All fixes are historical;
pretraining overlap remains unknown. Existing B/B2 repositories were excluded.

The code and tests are exact upstream bytes. These are selected native regression
functions, not complete upstream test suites. Generated packaging metadata for
`platformdirs.version` and `humanize._version` is supplied explicitly;
no behavior implementation is substituted. Global repository conftest/plugins
are excluded, and each selected function's fixtures and complete parameters
remain in the original test file. The platformdirs fix reuses tests already in
its parent revision; the record does not falsely attribute those tests to PR 721.

## Runnable material entry

After extracting `complete-originals.tar.gz` into a new directory:

```sh
python3 -I -B source_materials.py --root /absolute/extracted-directory --output /absolute/new-material-directory
```

`load_materials(directory)` also returns the same four records directly.
It verifies every upstream file and the original native receipts, then exposes
before/after code, deterministic repair diffs, the original test functions,
license notices and failing/passing observations. The output
`MATERIALS.jsonl` is **repository repair material**, not a claimed historical
agent trajectory or a fabricated prepared-v3 model observation.

These materials can supply A-only tasks for the next E1/E2 candidate. To measure
student experience, first run the actual current student and retain its own
actions and native feedback. Historical maintainer diffs cannot replace that
on-policy execution. A later answer/trajectory SFT comparison must freeze shared
information, rendering, tokenizer, initialization and actual training cost.

## Original E5 continuation

The entry retains existing E5 sizes **1/4/16/64** and regimes
**fixed_total / fixed_per_source**, with the same lexical source-ID prefix rule
as `composition.py`. Consequently the one-source point is Rich; it was not
picked for its observed outcome. The proposed schedules are concrete:

| Regime | 1 source | 4 sources | 16 / 64 |
| --- | ---: | ---: | --- |
| Fixed total | 32 update units, 32 per source | 32 update units, 8 per source | blocked: 12 / 60 sources missing |
| Fixed per source | 32 update units, 32 per source | 128 update units, 32 per source | blocked: 12 / 60 sources missing |

These are planned update units, **not executed training** or demonstrated
compute matching. Padded tokens, target masks, verification opportunities and
actual MAC/token cost still need to be frozen with the coding candidate.
The existing numeric composition runner can implement the 32/32 or 32/128
schedule with its original round-robin logic, matched `passes` and
`max_examples`; caps alone do not ensure actual equal work. It also requires
real preaction features, named class labels and future selection/confirmation
observations. None are invented here. That small classifier's accuracy is not a
coding-capability curve.

Old B and B2 are exposed diagnostics. They are not new training sources and must
not determine source choice or be reused as fresh confirmation. A prospective
coding experiment needs new source-separated evaluation and must retain NoUpdate.

## Cost and retained originals

Acquisition and isolated dependency setup took **83.328471716 s**.
The native replay owner took **29.860169452 s**, with
**29.321943 s** completed child CPU. These are disjoint stages; nested download,
setup and test-child timings are not additional wall time. All eight original
case timeouts and 15 observed failures remain in the archive.
Model calls and training updates are **0**. Energy, money and full-system
overhead remain unknown.

The complete archive includes original public API metadata, Git blobs, both
source/test/license snapshots, exact dependency wheels and version records,
all eight raw stdout/stderr/JUnit/owner receipts, the material entry and durable
runtime statuses. The per-file index binds every original; only redundant
installed-environment and pip-cache copies are omitted.
