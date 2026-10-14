# Source-wise conservative fallback for CPU FIFO video microbatching

This is an **exploratory** continuation of the existing arrival-aware CPU Conv2d
proxy experiment. It DOES NOT sample fresh sources or execute pretrained CLIP,
and it DOES NOT certify future p95, energy, native NDU, or deployment.

## Motivation

The earlier `choose()` uses the median of 2–7 calibration repetitions and
accepts a batch when its median p95 is >=5% better than scalar, subject to a
first-response and total-wall guard. A batch can pass while some individual
repetitions or source groups regress; the previously revealed heldout runs
indeed have sparse-arrival p95 regressions. This continuation does **not** use
those heldout labels, nor fit on heldout latency, to select its own policy.

## Predeclared secondary conservative choice

All five original FIFO strategies `(cap, wait_ns) = (1,0), (2,0), (4,0),
(4,2_000_000), (4,8_000_000)` remain physically executed; new analysis is
computed **after calibration, before holdout dispatch** and included in the
same frozen choice seal. The already-trained Reader and random frozen Conv2d
network are unchanged. No additional media decoding/encoding is needed to
compute the secondary policy; shadow cost is already charged by the parent.

The new source-guard accepts a non-scalar policy only if ALL hold in each
matched calibration repetition:

- at least **two separate calibration source videos**, each contributing at
  least four cells to that workload (otherwise choose scalar);
- candidate whole-workload p95 <= 0.95 x scalar p95;
- candidate first response <= 1.5 x scalar first response;
- candidate whole-run wall <= 1.1 x scalar wall;
- each observed source video's p95 <= 1.05 x its scalar counterpart's p95,
  using paired case identities and release times in the same repetition.

Among surviving policies, choose lowest median p95, then original grid order.
If none survive, conservatively select `1:0` (single Cell). For workloads with
only eight samples drawn from one video, the required independent second
source is missing; **no optimistic source extrapolation is allowed**.

Per-source measurements share one nonpreemptive FIFO queue and global frame
cache, so the source measurements are dependent. Two calibration source videos
are grossly insufficient to certify population tail risks; this is a strict
observable stability filter, not a probabilistic risk bound. A separate pure
stdlib auditor rederives the choice and all CPU/cache records without the
candidate selector or Torch models.

## Evidence boundaries and costs

The earlier comparison's heldout video sources and timing have already been
seen by research iterations. This continuation treats any improvements or
regressions on the SAME two holdout videos as a **retrospective exploratory
diagnostic**, not a fresh confirmatory test or independent resource win.
New independent public source families/recording dates and a real CLIP runner
remain necessary before considering product timing or broad NDU claims.

All parent branches, fixed-depth/threshold/value baselines, full original
selector and physical calibration/holdout arm runs remain. The new guard only
adds CPU bookkeeping. No altered CURRENT, FinalUse, deployment permissions,
or actual external actions.
