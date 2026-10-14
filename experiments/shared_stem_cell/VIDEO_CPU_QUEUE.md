# Source-disjoint CPU arrival-aware multi-Cell queue experiment

This is a **research-only single-process arrival replay**, not a concurrent HTTP
server, deployed scheduler, a pretrained CLIP experiment, or evidence of model
capability. It closes a gap in the previous CPU microbatch tests: those studies
assumed **every Cell arrives at exactly time zero**. Under sparse arrivals,
waiting to fill a microbatch can waste time, and a batch size that worked on
one calibration source can increase held-out p95 latency.

## Fixed experiment and competing policies

Original ten source videos and exact source SHA, cohort and six/two/two source
folds are unchanged. Six sources supply Reader training targets, two disjoint
sources calibrate queue policy **without labels**, two further sources supply
sealed predictions before held-out accuracy/NLL scoring. Release offsets come
ONLY from the declared workload's case index; class or source content cannot
modify them. All rows retain their original eight source-bound frame identities.

The candidate queue policies are immutable, each `(maximum Cells, maximum
admission wait in ns)`:

```
(1, 0)       # immediate scalar FIFO strong baseline
(2, 0)       # batch only requests already released
(4, 0)
(4, 2000000) # up to 2ms admission wait from FIRST request's release
(4, 8000000) # up to 8ms admission wait from FIRST request's release
```

Declared arrival patterns are burst (0ms gaps), 4ms gaps and 12ms gaps. Fixed
Reader inference depths are 2 or 8 frames. One **persistent frame-feature
cache across all dispatch groups in an arm** is important: it is not re-created
for every microbatch. Each arm uses a separate cache so competitor arms are
charged independently; no cross-arm/shared-test caching is claimed.

The FIFO worker sleeps until scheduled arrivals, admits only released Cells,
does not preempt a batch, and keeps arrivals that occur during its computation
queued for the next batch. The group deadline is anchored to the first queued
release, not reset each time the worker is late. Actual per-Cell completion is
measured against **scheduled arrival time**, including queue delay, admission
waiting, PIL/bytes validation, actual frozen Conv2d, feature cache, and a
trained shared GRU Reader. All 5 options are actually executed in counterbalanced
order for each workload on BOTH folds. Timers are process self-reports, not
independently attested CPU energy or a real multi-thread network service.

On calibration records only, a non-scalar option must (i) improve median p95
response latency by >=5% versus scalar, (ii) keep the first response within
1.5x the scalar first response, and (iii) not increase total wall by >10%.
Among eligible options select minimum median p95, then first response, then
predeclared grid order. If none qualifies, **choose scalar**. This rule is a
small-sample exploratory criterion, **NOT a latency/risk certification**.
Selection is sealed BEFORE held-out timing or labels. Held-out measurement
cannot alter the chosen batch policy or reopen the grid.

## Cost and negative result retention

Log every group's ordered Cell IDs, frame SHA list, cache misses, physical
forward calls, admission deadline, dispatch/completion clocks and response
latencies; plus full source-file bytes processed, proxy Conv2d and PIL time.
Report ALL five policies on calibration and holdout, not just the chosen one.
All calibration/holdout runs and the Reader's training and feature-extraction
work are charged. This first protocol deliberately fixes `warmups=0` so no
unsealed warmup costs enter the record; round order is counterbalanced. The
published `study wall` includes preparation, training, all controls, analysis,
and report construction, excluding only the final report file write.

Record both successes and **held-out regressions** without retrospectively
changing the selected policy. Selected-policy improvement is NOT an operational
claim: there is no confidence interval or external service-level guarantee, and
8/16 synthetic sources cannot establish population generalization.

- Source frames in the local fixture are GENERATED, not 360action MP4 content.
- The tower is a real CPU `torch.nn.Conv2d` with RANDOM frozen weights, NOT CLIP.
- No automatic retries, new NDU subject, effect authority, CURRENT change,
  reader topology activation, independent retention, speech/video generation,
  GPU peak memory, energy, or FinalUse qualification.
- The source repository's license has not been established. **Neither MP4s
  nor derived images are uploaded as CI artifacts.** Only hashed identities,
  prediction/cost JSON, test logs, and independent audit results are retained.

## Reproduce

On a previously staged explicit `public_video` root (source files and manifest
already verified), run with a local CPU thread limit of one:

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m experiments.shared_stem_cell.video_cpu_queue \
  --root "$RUNNER_TEMP/hepta-video-study" \
  --output "$RUNNER_TEMP/hepta-video-study/cpu-queue" \
  --calibration-rounds 3 --evaluation-rounds 4
python -m experiments.shared_stem_cell.audit_video_cpu_queue \
  --root "$RUNNER_TEMP/hepta-video-study" \
  --output "$RUNNER_TEMP/hepta-video-study/cpu-queue"
```

The auditor uses only the Python standard library (no repository scoring,
model, timing or selector implementation), and works on a source-manifest,
cohort, dataset metadata and result JSON copy **without images or weights**.
It recomputes actual requested frame SHA sequences, cache misses, batch counts,
record arrival/completion/latency, p50/p95/p99, the precommitted calibration
choice, held-out accuracy/NLL, and total charged physical work. Self-consistent
fabricated wall-clock samples cannot be independently authenticated from JSON;
that is a separate hardware measurement requirement.
