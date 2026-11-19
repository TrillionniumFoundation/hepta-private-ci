# Six real C2 checkpoint recovery diagnostics: d706 attempt001

**This attempt completed all six recovery diagnostics with 26 physical optimizer
calls. It adds zero independently complete C2 training replays. Scientific
admission remains `HOLD_NO_GO`.**

The executed protocol is the unchanged #6130 source
[`5cb83d9c76beedf4c1c917e4bf561f5f26261ce7`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/5cb83d9c76beedf4c1c917e4bf561f5f26261ce7/qualification/hcsn_differentiable/replay_v1).
The source identities in [FIXED_SOURCE_MANIFEST.json](FIXED_SOURCE_MANIFEST.json)
were checked against Git blob identities before execution and against native
files before and after execution. No selected checkpoint, numerical threshold,
worker protocol, or original C2 result was modified.

## What actually ran

For each of the six selected real original checkpoints, a fresh reference
process restored the checkpoint and ran two training batches. A second process
independently restored the same original checkpoint, ran the first batch, and
saved model, Adam, RNG states, and the exact next-batch cursor. A third fresh
process restored those saved bytes and ran the second batch. Thus each pair
advances the same logical training state by two steps while consuming four
physical optimizer calls. The six diagnostics consumed 24 calls.

The declared first-fit controls consumed another two calls: one continuation
omitted Adam state, and one producer exited with code 73 after a real Torch
save, flush, and fsync but before canonical publication. The omitted-Adam
continuation differed in model and optimizer state. The crashed producer left
no canonical `state.pt`; its retained private temporary decoded to the real
one-step producer state.

| Fit | Original epoch | Original Adam step | Final Adam step | Full state equality | Physical calls |
| --- | ---: | ---: | ---: | --- | ---: |
| hcsn-s101-lr0.001 | 116 | 1392 | 1394 | Exact | 4 |
| hcsn-s101-lr0.003 | 76 | 912 | 914 | Exact | 4 |
| hcsn-s211-lr0.001 | 126 | 1512 | 1514 | Exact | 4 |
| hcsn-s211-lr0.003 | 50 | 600 | 602 | Exact | 4 |
| hcsn-s307-lr0.001 | 127 | 1524 | 1526 | Exact | 4 |
| hcsn-s307-lr0.003 | 72 | 864 | 866 | Exact | 4 |
| Omit-Adam control | — | — | 1 in fresh Adam | Difference detected | 1 |
| Crash-before-publication control | 116 | 1392 | 1393 in private state | Matches producer | 1 |

Every reference/resume pair also has the same raw Torch file SHA256. The
identical model/Adam/RNG/cursor states and batch/loss/gradient receipts are in
[SUMMARY.json](SUMMARY.json). [SUMMARY_REPARSE.json](SUMMARY_REPARSE.json) is a
separate arithmetic reparse; it is not presented as a tensor audit.

[INDEPENDENT_AUDIT.json](INDEPENDENT_AUDIT.json) was produced by a separate
read-only native process running [audit_replay_originals.py](audit_replay_originals.py).
It decoded 26 Torch checkpoint files, including the six frozen original inputs,
checked all six full states bitwise, checked the actual Adam counters, verified
the controls and 554 distinct bound source/data inputs, and counted 26 physical
optimizer calls. All six final models differed from their original states.
This audit performed zero model forwards and zero optimizer calls; its native
wall time was 3.842779862927273 seconds. It is an independent readback of the
same attempt, with no independent future task denominator.

## Execution identity and resources

The native attempt directory is
`/home/qian-qi/hcsn-c2-real-replay-20261112-d706-attempt001` on `desktop`.
The terminal identity is
`dpty-97b62bd80e16bfacc031131f5226dea8c3e65618c1e6968c7eb32b3a5cbd03ed`;
the stable request key is `c2-d706-fixed-5cb-real-replay-attempt001`.
The launch acknowledgement is retained in [NATIVE_LAUNCH.json](NATIVE_LAUNCH.json).
The attempt started at 2026-11-12 06:33:31 UTC and returned exit 0 at
approximately 06:48:37 UTC. [EXIT.json](EXIT.json) records no timeout and
905.7613612581044 seconds of outer wall time.

The interpreter was Python 3.12.3 with Torch 2.8.0+cu128, running on CPU with
`CUDA_VISIBLE_DEVICES` empty. The original protocol allowed two concurrent
workers, one CPU thread per worker, 8 GiB address space, a 300-second worker
budget, and a 330-second per-process outer timeout. The enclosing invocation
had a 4,500-second safety timeout. It completed before that bound.

[orchestrator-time.txt](orchestrator-time.txt) records 1474.17 user seconds,
157.19 system seconds, 15:05.71 wall time, and 3,655,716 KiB maximum resident
set size. This is GNU time's maximum single-process RSS statistic, not the sum
of concurrent process peaks. It includes import/setup and the two controls for
this attempt. Audit/archive/transfer work is separate. These measurements do
not establish whole-program cumulative cost, power, energy, or lifecycle cost.

The original C2 controller job `1a1c74f3308-be2a-75` was not restarted. Its
missing confirmed terminal, incomplete output accounting, and original C2
qualification are not repaired by this diagnostic.

## Other attempts remain separate

The other thread's fixed evidence at
[`a832b028abdf1a1c9ab66534332457c6d76a91ca`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/a832b028abdf1a1c9ab66534332457c6d76a91ca/qualification/hcsn_differentiable/evidence/real-checkpoint-replay-native-20261112)
records two separate native attempts: `1a1ce727d17-2564-167b` and
`1a1ce768bc3-2564-1695`. Both received cancelled status with signal 15 and no
complete recovery report. The first retained a PREEXECUTION and reference
launch output. Their actual optimizer calls are **UNKNOWN**, as are the cause
of cancellation and descendant termination. Cancellation is not a zero-call
receipt. This d706 attempt's 26 calls do not replace or erase their unknown
cumulative cost. Across attempts, total physical optimizer calls and total
cost remain unknown. Those jobs and their branch were not changed here.

## Raw evidence and verification

[NATIVE_ORIGINALS.zip](NATIVE_ORIGINALS.zip) is the exact native attempt-directory
archive: 128 members and 10,976,581 bytes, SHA256
`d17e71b766631f3789dcb43bdd312dacfbc4ea0ce7e4fc14074587584900a2fe`.
Its Git blob is `deededd79d8a72d55059e7b7c439f66434a679f0`.
[MANIFEST.json](MANIFEST.json) binds each of the 127 archived files; the archive
also contains the manifest itself. [ZIP_RECEIPT.json](ZIP_RECEIPT.json) records
the member count, archive hash, and native replay/audit exit codes.

The ZIP retains the pre-execution plan, all six original checkpoint copies,
all 18 reference/producer/resume checkpoint files, negative and crash states,
worker reports, stdout/stderr and exit receipts, native source snapshot,
independent audit source/output, and native timing. Original source/data inputs
outside the attempt directory are identified and hashed in PREEXECUTION and
were checked by the audit. Their complete raw files are not all duplicated in
this attempt-directory ZIP; this archive alone is not a portable training-data
bundle. The upstream a832 evidence separately records its frozen input export.

The archive was verified on the native host, then uploaded as an immutable Git
blob using the existing authenticated `ProfHepta` account. The uploader verified
the archive's SHA256 and length, computed its Git blob SHA from the actual bytes,
and required GitHub's returned SHA to match. It did not change refs. The
retained [ARCHIVE_UPLOAD_PTY.json](ARCHIVE_UPLOAD_PTY.json) records exit 0,
complete output, the matching blob SHA, and 17.557805522112176 seconds of upload
time. This is not a claim that the coordinating agent downloaded all 11 MB.

Read/launch acknowledgement timeouts and unsuccessful chunk reads are preserved
in [TRANSFER_STATUS.json](TRANSFER_STATUS.json). The same request key was used
to reconcile the archive-upload acknowledgement; the eventual admission was
`reused=false`, followed by a confirmed terminal. No new model invocation was
launched to compensate for a transport timeout. Small native originals were
recovered with an immutable 41,060-byte asynchronous read payload and checked
against its SHA256 and each original file's SHA256.

## What remains open

This is a completed checkpoint-continuity and local crash-publication
diagnostic for the selected old-kernel states. The complete independent C2
training replay denominator remains **0/6**. No new D evaluation or confirmation
E access was performed by this protocol. The ordinary episode reader loaded D
as declared by the frozen source; no independent efficacy claim follows.

Remaining work includes a fully specified and independently completed C2
training replay with terminal and stopping-rule evidence, plus qualification
of any replacement timing kernel: old-posterior migration, the original 14,336
posterior domain at the unchanged continuation-value gate, first-hit/reset/age/
tail behavior, complete gradients, and real retraining. This attempt supplies
none of those missing denominators and changes no scientific admission gate.
