# Real-time and source-level research execution (2026-11-12)

Parent: PR #6097, `1eac6794355fa01a3e051776c5598a13ac612073`.
Scope: Python float reference and declared-source experimental analysis only.
Qualification: **SHADOW_ONLY / DENY_ALL**. Model inference/training: **0**;
new independent efficacy tasks: **0**. No scientific or production gate closes.

## Implemented behavior

- `real_time.py`: reward occurrence discount, exponential state response,
  update interval and eligibility decay use separate actual-time parameters.
  Verify owner/clock/boot time envelopes before classifying feedback as future;
  unavailable payload does not enter the candidate view. Visible action/source/
  model/group bindings and chronology are checked before credit computation.
- `source_contrast.py`: freeze task roster, source clusters, model/evaluator and
  opportunity budgets; compare original unrouted information bytes and their
  availability. Route assignment is separate from information identity.
  Missing/UNKNOWN outcomes retain the planned denominator and withhold statistics.
  Source means use equal source weights; repeated seeds do not add sources.
  Confirmatory p remains null because provenance/randomization are not attested.
- `learning_progress`: report first-observed attainment intervals, retaining
  nonattainment as right-censored; no imputed success or exact crossing time.
- `FOUR_TRACK_PROTOCOL.md`: fixed comparisons, independent replay factors,
  information-acquisition controls, new-learning/retention matrix and phase gates.

## Actual verification

Local Python 3.12.14: **119/119** tests, exit 0 (102 inherited + 17 new).
Original command/output, platform, elapsed wall time and all 24 Python file
SHA-256 values are retained in `REAL_TIME_SOURCE_LOCAL.json`.
`just fmt` ran from `codex-rs`, exit 0; the upstream formatter has no owning
group for these qualification paths and changed no source bytes. Its exact
output is in `REAL_TIME_SOURCE_FORMAT.json`. `git diff --check` passed.
No tests were rerun after formatting; every tested Python source remained identical.

The ai395 replication was requested once with a stable operation key;
its remote outcome is unconfirmed until original status and logs are read back.
The local result above is independent of remote completion. Hosted CI likewise
requires its own exact commit/job evidence and is not inferred from this report.

## Remaining execution boundaries

Source grouping, original bytes, exposure counts, clock times and ownership are
input declarations; hashes do not authenticate them. Persistent cadence/CAS,
Q24 numerical equivalence, ordinary native owner integration, independent future
B, actual MEM/ACT replay, PERC/VERIFY effects and later C/cold recovery are open.
Existing HPCA negative results remain unchanged; #6132 development data does not
become independent confirmation by being reprocessed through these interfaces.
