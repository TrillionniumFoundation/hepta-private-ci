# Causal execution beyond the v7 single-step interface

This directory adds executable development support for the common-content
interface. It does not restore v6, qualify a new AV cohort, or establish an
analytic-core benefit. Every returned execution receipt explicitly has
`scientific_confirmation=false`.

## Implemented behavior

`planning.py` enumerates bounded adjacent-prefix READ/WAIT paths. The same
`choose_plan` function accepts core and direct-cache forecast adapters. A
forecast estimates actual terminal correctness of the common content head.
The service model separately supplies elapsed time, deadline risk and the
expected number of requests actually issued. These fees are charged once.
The executor commits the complete selected path, rather than silently using a
different replanning policy from the one that the forecast valued. STOP wins a
tie. A WAIT-only path cannot change this time-independent content head's
correctness forecast.

`execution.py` charges the compulsory first audio request and every subsequent
issued request, including failed, rejected and late work. Only completed,
accepted observations reach the common cache or core. A late request cannot
change the serialized output: output is frozen and flushed before that work is
drained. Actual output computation/serialization can still miss the deadline;
the receipt records that failure instead of declaring an ideal deadline met.
The complete process cost includes draining. A failed output sink also drains
owned pending work before the exception escapes.

WAIT advances only scheduling time. Receipt schema v2 records both the new
modality-prefix interval and the increment in the maximum accepted source
prefix. The latter is passed to `core.accept`. Audio prefix 1 followed by video
prefix 1 therefore represents two modality observations but one global source
second, independent of their order. The second observation still updates
content when its global time increment is zero. This is an explicit v8 time
convention, not a claim about the unavailable v6 dynamics.

The content head receives only `VisibleContent`. The value adapter receives
that cache, its declared optional `CoreSnapshot`, and a public `Plan`. It does
not receive the service, full recording, pending result, or target label.
Python adapters are trusted research code, not a sandbox against a malicious
implementation that reads undeclared global variables.

## Adapter interface

The existing v7 `VisibleContent`, `CoreSnapshot`, `StopEvaluation` and
`CorrectnessValue` classes are reused without editing v7 files.

| Component | Interface |
| --- | --- |
| Common content head | `evaluate(content) -> StopEvaluation` |
| Semantic forecast | `kind`, `reader_id`, `evaluate(content, state, plan) -> CorrectnessValue` |
| Common service model | `estimate(content, plan, now, deadline) -> ServiceEstimate` |
| Core | `initial(content)`, `accept(state, updated_content, observation, global_source_increment)` |
| Requested feature service | `request(Read, clock) -> pending` |
| Pending work | `wait_until(deadline, clock) -> ReadResult or None`, `drain(clock)` |
| Output | A callback accepting serialized bytes and returning after actual flush |

`ServiceEstimate` requires `additional_seconds`, `deadline_miss_probability`
and `expected_requested_reads`. The latter may be fractional but cannot exceed
the path's read count. This matters because a timeout/failure can prevent later
steps from being requested. Realized fees always use the observed request
count, independently of the estimate.

## Verification and retained evidence

The behavioral suite exercises mandatory/failed charging, future/duplicate
rejection, committed multistep paths, no-content WAIT, global source-time
ordering, shared controller behavior, expected issued-request fees, output
flush latency, and drain-after-output semantics. Its final 15 tests are in
`validation/tests003/`. Earlier receipts remain: `tests001` records a test-only
binary floating-point equality failure, repaired using a stated tolerance;
`tests002` has the preceding 13-test pass.

`validation/source002/` preserves the exact earlier scheduler sources used by
the first actual subprocess probe. Later independent review added expected
issued-request costs and explicit global source time. The first probe uses
fixed plans and no core, so it does not test those subsequent changes.

The real controlled worker probe is recorded in the sibling directory
`economics/validation/scheduler_live/`. It uses computed fixture features,
not a media encoder. The normal case executes three paid/accepted reads and a
WAIT; the late case pays its first audio request, outputs before the late
payload, and drains afterward. Its approximately 0.2009-second output misses
the 0.2-second deadline and is correctly recorded as late.

## Historical real-data integration

`historical_service.py` supplies requested prefixes from the recovered V3
prepared real AV arrays. A logical clock uses an explicit simulated 1 ms/read;
this is not a measured latency. A real clock waits for the prefix's source
release and measures actual array selection/copying. Neither route decodes
media or reruns original acoustic/visual feature preparation.

`historical_probe.py` fits current correctness and a simple cache-level future
correctness table on the historical validation split already used to select
the V3 head. It then runs a deterministic historical actor-by-label subset in
three modes: audio-only common head, full common head, and cache-value control.
The exact subset and source hashes are written before predictions. A separate
real-clock subset crosses two actors and two labels for each task. Its output
markers measure source-to-flush latency, while the enclosing cost receipt also
includes fitting, imports, preparation, observation, control, serialization and
teardown.

The audio-only mode is an execution ablation of the shared joint head. It is
not the missing v6 strong-audio reference. The fitted cache table is a simple
development diagnostic, not an established strongest no-core comparator.
The tasks remain V3 six-class emotion and same-recording AV binding, not v6
five-class emotion and statement binding. Old actors, recordings and pairs do
not become new independent objects through this replay.

Run from the repository root with the documented restored runtime, for example:

```bash
PYTHONPATH=/tmp/hcsn-torch-runtime:recovered/v3 \
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
python3 -m experiments.hcsn_v8_execution_20261101.economics.worker_cost \
  --out /tmp/new-historical-cost --timeout 90 -- \
  python3 -m experiments.hcsn_v8_execution_20261101.scheduler.historical_probe \
  --out /tmp/new-historical-evidence
```

Directories must be new; earlier evidence is never overwritten. For portable
reproduction use a compatible Python installation providing NumPy and PyTorch,
with `recovered/v3` on `PYTHONPATH`, instead of the task-local runtime path.
Use the enclosing process CPU once. Nested fitting/component timings explain
that total and must not be added to it again. Original decoding/training,
complete deployment-family memory and directly attributable device energy
remain separate unclosed measurements.

## Recorded historical integration result

`validation/historical001/` contains the frozen protocol, both fitted adapter
tables, all 48 logical episode receipts, all eight real episode receipts and a
machine-readable summary. `validation/historical_cost001/` is the enclosing
cost record. Source identities remained unchanged through both execution and
cost collection.

| Historical task | Mode | Correct / objects | Mean requested reads | Mean logical utility |
| --- | --- | ---: | ---: | ---: |
| Six-class emotion | Audio-only common head | 3 / 12 | 3 | 0.174995 |
| Six-class emotion | Full common head | 5 / 12 | 6 | 0.281657 |
| Six-class emotion | Cache-value control | 6 / 12 | 4.666667 | 0.393325 |
| Source binding | Audio-only common head | 2 / 4 | 3 | 0.424995 |
| Source binding | Full common head | 3 / 4 | 6 | 0.614990 |
| Source binding | Cache-value control | 2 / 4 | 2.5 | 0.442492 |

The four-pair binding subset above does not retain balanced video marginals;
its score is not a balanced binding quality result. The deterministic audit is
in `historical001/POSTHOC_SUBSET_MARGINAL_AUDIT.json`. The supplemental complete
historical-set replay below repairs that sampling limitation without changing
the first protocol, outcomes, or fitted adapters.

Logical utility uses the declared simulated service clock, not measured
deployment latency. Fixed-path scheduler predictions exactly match the
standalone old head on the same causal rows. The 16 selected task objects come
from only 12 unique original recordings and two actors; repeated modes and
binding pairs do not increase those independence counts.

All eight actual source-clock episodes made and accepted six requests. Their
observed post-flush markers were 3.007786991–3.045726022 seconds, below the
unchanged four-second deadline, with exact standalone-head parity. Recognition
was 0/4 on the selected emotion subset and 3/4 on binding. These negative
emotion outcomes are retained without changing the selected subset.

The complete enclosing process used 16.068374 CPU seconds and 81.925233439 wall
seconds on the shared host. This includes imports, data loading, adapter
fitting, 48 logical episodes, eight live episodes, coordination and evidence
serialization. It is not a per-episode inference measurement. The two nested
adapter-fit CPU readings are 0.148797387 and 0.274495601 seconds; they are not
added again. All eight timing markers have valid observer bounds. Complete
waited-task CPU coverage passed; full process-family RSS and attributable
device Joules remain unavailable. The largest single-process high-water is
184,467,456 bytes; the registered-subset RSS sum is a different measurement
and must not be relabeled a complete family peak.

### Complete balanced historical binding set

`balanced_binding_replay.py` loads the exact earlier fitted tables without
retraining and executes every one of the original 24 binding pairs. The 72
new logical executions use the same inputs in all three modes; audio and
video source marginals are equal across labels. All final scheduler outputs
exactly match independently populated common-head prefixes.

| Mode | Correct / 24 | Mean requested reads | Mean logical utility |
| --- | ---: | ---: | ---: |
| Audio-only common head | 12 | 3 | 0.424995 |
| Full common head | 13 | 6 | 0.406657 |
| Cache-value control | 14 | 3.75 | 0.498117 |

`validation/balanced001/` contains the protocol, unchanged-model hashes,
marginal counts, all raw episodes and summary. The enclosing receipt in
`validation/balanced_cost001/` records 3.244636 CPU seconds and 6.933083143 wall
seconds. There were no additional real-clock episodes or new fits. This is
still 12 old recordings and two old actors. It is a more complete historical
diagnostic, not new AV confirmation or an analytic-core comparison.

The six-read schedule is not the strongest fixed-cost baseline: this binding
task ends at 1.5 source seconds, so audio/video prefix 2 already contain its
final features. Prefix 3 adds requests without new content. No qualified
economic advantage is claimed against that deliberately complete schedule.
