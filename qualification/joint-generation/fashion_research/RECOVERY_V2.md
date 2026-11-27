# Source recovery v2: lifecycle receipts and phase ownership

This is a no-data correction of the independently reviewed `1d858c66eec4`
implementation. The old `FROZEN.json`, protocol, access denials and verification
receipts remain unchanged. No D measurement or Fashion intake has started.
The active source is bound by a new `FROZEN-recovery-v2.json`; its lineage records
the original freeze SHA256
`1499451236c1ffab1cde056f1f4af8b8c62ecf64875a9dc35fa924bbefdec097`.

Two concrete defects were corrected:

1. The launcher previously sent SIGTERM without a worker handler, so `finally`
   and the worker receipt could be skipped. Stage/seed progress is now atomic.
   The launcher independently reaps every stop and writes an atomic terminal
   record with `partial`, reason, actual worker status, started/completed/unrun
   stages and started/unrun seeds. A worker's original receipt is retained as
   `worker-result.json`; it cannot turn a requested stop into success by exiting0.
   A missing worker receipt or direct SIGKILL still produces a launcher fallback.
2. Policy-row mapping and fold preparation previously occurred after shared150
   had closed but before seed450 began. They now precede the shared closing
   timestamp. Each build reuses the preceding exact closing timestamp, assigning
   transition bookkeeping to that build without a free preamble or double count.

CPU/RSS cap termination sends immediate SIGKILL, without additional flush grace.
A non-resource external stop may request SIGTERM and bounded wall-time flushing;
the unchanged CPU/RSS cap remains checked throughout and can immediately kill it.
Worker SIGTERM/SIGINT handlers permit controlled `finally` where possible and
restore previous handlers. The launcher fallback does not depend on them.
Termination, reaping and required receipts remain method work. Actual overshoot
stays a nonzero failure; sampling is not a zero-overshoot guarantee.

Two integration defects found by the targeted review were also fixed: the
supervisor no longer creates the output directory before the worker's preflight,
and an explicit `reaped` flag ensures blocking `wait4` on exception paths after
WNOHANG, retaining actual CPU and signal status.

New tests use only tiny Python subprocesses, hand-made clocks, and mocked intake.
They cover TERM followed by worker0, ignored TERM followed by KILL, self-SIGKILL,
immediate CPU-cap kill, worker handler/finally restoration, output ownership,
supervisor-exception reaping, contiguous phase ownership, and a shared140→151
second case that fails before any model construction. They do not read Fashion
files or create the real once-only marker. Existing synthetic model/data/wire
tests remain software checks, not research outcomes.

The parent's independent dot review reported42 additional hand-made directional,
detach and wire/risk checks on the old source. They were not run here and are
not included in local test counts. No model, data, loss, noise, route, seed,
scientific gate or budget was changed by this recovery.

The original complete1800 CPU-second/2GiB limits and shared150/seed450/content300/
policy150 sublimits remain. The original protocol is preserved; v2 adds only
source-recovery notes. Other five strong-static arms, SELECT, SCREEN, official
TEST, formal confirmation and AV remain unrun. Two official TRAIN file HEAD403
denials were not retried or bypassed. The next data-dependent action still waits
for lawful local TRAIN files, followed by the single frozen D preprobe.

From `qualification/joint-generation`, the same no-data smoke command applies:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 python -m fashion_research.launch --smoke
```

Independent review/publication is separate R&D. Versioned verification receipts
bracket their own commands only; they do not claim to meter all development.
