# C2 resource renderer v2: preparation only

**This version has not rendered actual results and has not been adopted for a
production execution.** The authorization template remains false. No real C2
result, model, E input, numerical oracle or synthetic scientific plot is read
or executed by preparation. The only new validation is source-text compilation.

## Narrow change and recovery scope

The original v1 plotting/report source and input guard were recovered from the
retained source text and matched their original byte counts and SHA256 hashes.
`SOURCE-RECOVERY.json` distinguishes recovered exact source from unavailable
old archive/test-receipt bytes. No old execution was rerun or recreated.
The frozen analysis plan is copied byte-for-byte from the restored published
repository, with SHA256 `4ccfa7cc21ec37312e48d095e8f4b7373c765dd6d33fa9314ce724d161e8b06b`.

The sole runtime change is the three extra independent outer-receipt checks in
`DIFF-v1-to-v2.patch`:

- `direct_child_CPU_complete` must be `true`.
- `total_attempt_CPU_unknown_or_lower_bound` must be `false`.
- `adopted_child_wait4` must be an empty list.

Thus an empty first/final process scan cannot hide a descendant discovered and
reaped in the middle of cleanup. The v2 producer rejects this case, and the v2
consumer now checks it independently. The plotting/report source is unchanged;
existing JSON schema names and SVG hash salt remain stable. Source hashes,
not those format names, identify this new prepared version.

## Future input and timing contract

The later root decision must bind both renderer modules, the exact analysis
plan, the actual supervisor source SHA, a new output directory, and exact
size/SHA256 identities for four files: the complete OS receipt, internal core
receipt, standalone RESULT, and complete output ZIP. The guard rejects changed
caps, unknown terminals, incomplete CPU, descendant cleanup, unreadable scans,
source changes, invalid ZIPs/manifests or missing artifacts before importing
matplotlib. It also checks the original resource RESULT/POINTS byte identities,
all 42 opportunities, seven core rows and supplied quality gates.

The analysis launcher child has a 120-second Popen-through-wait4 envelope,
including its worker and inner receipt write/exit, with one worker/thread and
512 MiB observed per-process RSS. The core receipt is only a nested prefix.
Actual subreaper/process tracking and both endpoint observations are required;
a default boolean cannot replace them. Supervisor metadata finalization has a
separate 30-second bound, and its full native envelope must later be observed
within 155 seconds. Its own written receipt is still a prefix, not its OS exit.
The future root render decision must bind that complete execution evidence.

## Presentation scope

No LR, mean, sample SD, median or training metric is recomputed. Both old
300/900/1800 views and old RESULT/POINTS bytes are retained unchanged. Existing
timed-before-training eligibility stays visible, and C2 never backfills the
old cuts. Missing observations are not zero-filled or interpolated.

New terminal quality uses the already-admitted common-LR table. HCSN requires
all six quality records to be independently admitted before selection can be
shown. Verified quality with inadequate training remains diagnostic and
explicitly marked HOLD; unverified quality remains missing. Sample SD is
variation across three initializations on reused subject D, not a confidence
interval. Figure and report titles identify D as the selection data, not
independent confirmation. A target-time median is shown only for 3/3 observed
complete-epoch crossings.

All six candidate opportunities, failed candidates and discarded partial work
remain charged. Quality-prefix clocks are distinct from complete C1/C2 wrapper
bills. Known cost lower bounds and unverified costs remain explicit; they are
not zero. Original startup/diagnostics are already included in original fit
costs. Historical tuning, extra probes, controller/preflight, independent
review and transport retain separate overlapping scopes. Process-wall sums
are not campaign calendar time or idle-host throughput. Incomplete original
CPU components remain incomplete, and observed per-attempt RSS is not
concurrent-tree RSS, target-time memory or GPU VRAM. Energy and currency are
unmeasured. Numerical and scientific admission remain HOLD.

## Deferred rendering

After a new exact authorization, invoke `render_c2_resources.py` with
`--authorization`, `--authorization-sha` and a new `--output` directory.
The false template is unusable. There is no automatic retry. The intended
outputs are PNG/SVG, a short Markdown report, exact accepted metadata copies,
and a render receipt. That receipt reports a main-entry timing prefix; full
external render cost and visual inspection must be recorded separately.

Compilation is new v2 preparation evidence only. It does not replace the
missing old v1 receipt, test the plotting backend, validate an actual resource
analysis, or establish production use of v2.
