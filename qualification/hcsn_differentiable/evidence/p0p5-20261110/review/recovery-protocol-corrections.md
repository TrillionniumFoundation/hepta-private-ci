# Independent review of the outage checkpoint

The four exact reviewed Git blobs are retained under `reviewed-recovery/` and
listed with sizes/SHA256/Git object IDs in `reviewed-recovery/INPUTS.json`.
They are time-stamped historical snapshots. Cloud access subsequently returned;
that does not change what was known when the snapshots were written. The original
CURRENT overlay is not applied to the surviving complete CURRENT.

The main treatment of unknown native status, lost acknowledgements, original
request keys, draft/unpublished release, pending CI, numerical HOLD, scientific
HOLD and baseline-only C1 is appropriately conservative. The GitHub asset check
is explicitly metadata matching, not a new byte download. The continuation tests
are described as implementation fixtures, not scientific results.

Three disclosures need correction in a later attachment rather than rewriting
the historical observation:

1. The original v8 controller is a generic nine-worker ThreadPoolExecutor with
   HCSN-first ordering, not a baseline semaphore. It initially permits three
   baselines while all six HCSN slots are occupied; later it may run more baselines.
   C1's separate maximum of three workers is a different rule.
2. Four hours is the nominal per-fit upper limit. Each original attempt has actual
   `hard_wall_seconds=min(14400,15000-dispatch_elapsed)`. A late attempt's C1 phase
   must inherit that smaller value. Actual common-budget opportunity and censoring
   require the per-fit records, not the nominal declaration.
3. C1 adds continued optimization and a source/preflight/controller phase after
   original cap observations. It does not add LR/seed/diagnostic choices, but
   saying it adds no tuning opportunity at all is broader than the evidence.
   Preserve the amendment and charge all new work.

Static review of the original unexecuted C1 controller intent (Git blob
`915340af31e0ef97f4d46b60a20f794228b3a1ad`) also found a zero-initialized
`formal_fits_started` field that was never updated, and an exception path where
`future.result()` could stop result collection while the pool still waited for
other already submitted work. The complete waited-child CPU could then coexist
with an incomplete attempts/outer-wall subtotal. These are source-review findings,
not claims that such failures occurred. Training is preparing a distinct controller
version with actual phase-process counts, exception harvesting and inherited
actual ceilings; the original intent remains preserved.

The independent v1 reviewer ZIP was recovered without byte changes. Its original
native preflight acknowledgement remains unknown and must be reconciled by the
original key. Local v2 reviewer validation is separate from any completed native
campaign review. No result here grants CI, training-domain or scientific admission.
