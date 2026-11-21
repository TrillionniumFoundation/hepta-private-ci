# Verification of sealed value-retention records

This stage verifies the already sealed five-fit value-retention study. It cannot
generate candidates, draw public schedules, fit a model, change mathematical
tolerances, reselect a policy or introduce a new utility comparison. The original
failed 55 CPU-second reader remains an immutable failed attempt.

## Execution and ownership

The new child has 175 CPU seconds soft and 180 CPU seconds hard. The whole
supervisor stage has300 wall seconds, including preflight and final checks,
with one thread, CPU7 and512 MiB address space. Import, authentication and persistence
costs count in the child. The parent separately records supervision and full-input
hash checks. There is one create-only attempt directory and no automatic retry.

This execution envelope is explicitly Linux-specific. `freeze_contract.py`
authenticates the exact original protocol and reader, all
members of MAIN/CONF/failed-reader attempts and every direct original protocol
pin. It reads bytes and JSON metadata only; checkpoint and array bodies are not
deserialized. The new source set, review/qualification records, source-reuse proof,
old failure, selected candidates and80 PUBLIC records are bound before execution.
Typed root admission also binds the successful13-test engineering process/result,
final-source static peer review and existing user authorization. Those references
are rechecked before and after execution; arbitrary extra evidence is insufficient.

`source_loader.py` compile/exec loads pinned original Python source without using
timestamp-based bytecode caches. `run_verification.py` retains the original `main`
and every mathematical function object. Only four module bindings are wrapped:

1. `configure_budget`: preserve the original55/60/120 contract checks while
   applying the separately frozen175/180/300 execution envelope.
2. `main_fit_check`: track fit entry, then delegate the exact original function.
3. `confirmation_fit_check`: delegate, then mark its returned result pending.
4. `primary_check`: persist the final completed fit, then delegate unchanged.

A pending result is not a fit-completion receipt. The original `main` performs
its two post-CONF chronology checks after the confirmation function returns. Its
next budget boundary or primary entry then persists the fit. No original budget
call exists between those chronology checks. The budget boundary flushes before
checking elapsed CPU, so a completed fit can survive a subsequent budget stop.
The signal handler does not flush, because a signal may interrupt those checks.
An interrupted fsync/write can still leave an incomplete record; it never counts
as completed. Every receipt uses exclusive creation and fsync of file and parent.

## Acceptance

The delegated `READER_RESULTS.json` is a mathematical-check record. It does not
represent successful execution under the old resource contract and does not
provide standalone new-stage acceptance. `STAGE_RESULTS.json` instead has status
`VERIFIED_PENDING_PARENT`, binds the new contract and all five fit receipts, and
requires the unchanged original global source/phase/seed/exclusion/statistical
checks. The parent verifies child success, finite resources, every receipt and
unchanged source/input bytes. Only then does it write `PROCESS.json` as COMPLETED
and a separate `FINAL_VERIFICATION.json` with PASS.

The existing native exporter pins the old55/60/120 reader process and cannot
consume this new format without a separately versioned integration. This stage
never calls a production owner, edits active weights or establishes financial
efficacy. Full verification does not turn exposed CONF schedules into a fresh
holdout for later candidate selection. KEEP/STOP remains an admissible outcome.

## Commands

The tests require the unchanged original source directory (public parent PR
files suffice); no private protocol, checkpoint, teacher or result is loaded:

```sh
python test_stage_controls.py --original-source ../weight_value_retention_20261121
```

Local paths are supplied explicitly. Draft and frozen contracts are new private
artifacts, never replacements for the original study:

```sh
python freeze_contract.py --mode draft --old-root ORIGINAL_STUDY --stage-root NEW_STAGE
python freeze_contract.py --mode freeze --old-root ORIGINAL_STUDY --stage-root NEW_STAGE --admission ADMISSION --evidence REVIEW --evidence QUALIFICATION
python supervise_verification.py --contract NEW_STAGE/PROTOCOL_FROZEN.json
```

The final synthetic suite combines new lifecycle controls and the original four
reader controls. Engineering qualification is separately budgeted; neither the
synthetic suite nor metadata freezing consumes the single real-reader attempt.
No CLI silently retries or removes an existing attempt to make room for another.
