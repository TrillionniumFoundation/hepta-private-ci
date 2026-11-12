# Evaluated Version progress V4 design

Status: independent preformat design over frozen V3 preformat inputs. Actual V3 Rustfmt completed with exit 0, but the complete 40-file after image is still being recovered by the root agent. These files are not represented as those formatted after images. No H operation, Rust build, native test, publication, or ordinary qualification was performed for this design.

## Consumed interface

`OriginalCircuitRetainedVersionClientV1::publication_progress(&self)` returns `Result<OriginalCircuitEvaluatedVersionProgressV1, OriginalCircuitRetainedVersionErrorV1>`.

The result enum is crate-private, reexported through the actual `circuit_feature_current::retained_publication::version` module hierarchy to `crate::OriginalCircuitEvaluatedVersionProgressV1`. Its only values are `Pending` and `ReadbackAvailable`. It has no signature, intent, publication, task, CURRENT, grant, source-owner, or fresh-execution getter.

The actual consumer is `cell_q24_candidate_stage_retention_selection.rs::prepare_evaluated_version`. Root owns that separate patch. A Pending or Busy result can only schedule another bounded request. ReadbackAvailable must be followed by the same client's existing complete `readback`, a present publication, and the original Root effect gate. It cannot checkpoint S/C or start an effect on its own.

## Protocol and refusal boundaries

The old three-cut wire file is unchanged. Its `Action` still has only Prepare and Readback. The evaluated request alone gains `PublicationProgress`, under its existing explicit evaluated purpose and `evaluation_head`. Progress has a separate response result type: it cannot deserialize Prepared or Installed results, and the original full response decoder rejects a progress request.

Both request and response keep the exact original initial binding, complete evaluated context binding, operation, evaluation head, request sequence, schema and purpose. The same original channel is taken, used and restored under the existing deadline, 128-frame counter and queued-cancellation fence. Any progress read permanently attenuates the client's prepare bit. Only a Busy progress error can restore that same original connection; denied, unknown, missing, malformed or unavailable results do not restore it.

The server validates the original material clock and already-bound complete cut. It does not bind a missing cut, take an initial T/B capability, read an owner, call CURRENT, take a phase or issuer, publish, or update any execution flag. The states are deliberately limited:

| Private actual host state | Scheduling response |
| --- | --- |
| No already-bound cut | ReadbackRequired; no owner binding |
| Lock busy | Busy; no assertion about a cut or CURRENT |
| Awaiting with no admitted preparation | Pending only |
| Awaiting after a failed admitted preparation | Uncertain |
| Prepared with issuer Awaiting or Requested | Pending only |
| Installed or Recovered with Published outcome | ReadbackAvailable only |
| Denied, Uncertain, absent phase, inconsistent combination | Refusal |

The last response checks still verify the original material clock, host lifetime, size bound and complete signed cut window. A pending hint is not evidence of current owners, and an available hint is intentionally compatible with a subsequently withdrawn actual publication. The mandatory full read must discover that withdrawal.

## Removal of one redundant private read

For an already-bound evaluated cut, `bind_original_predecessor` now checks the fixed purpose, initial binding and complete original cut signatures/window without adding another live D/T/B read. Every actual caller then executes its own original transaction. `read_original` is byte-for-byte unchanged: it performs live D/T/B reads before and after, then the final physical Source/Cell/CURRENT and Artifact observations. The three-cut branch retains its previous additional `require_cut_current` call.

This is not a cache of a prior CURRENT result. No proof is retained across public API operations or across Root's FinalUse network call. The initial owner binding still consumes the original Dataset, Trainer and Evaluator inputs exactly once. The UFCS correction in the Selector factory identifies the actual physical readback receiver for the unmodified typed caller verifier.

## Static budget, not a runtime claim

Counts below are logical complete read transactions at the Version boundary. They are not yet an end-to-end channel proof and exclude Root, S/C internal traffic and any multiplication inside B or SourceBound Training.

| Version operation | V3 D/T/B | V4 design D/T/B |
| --- | --- | --- |
| Initial Prepare, including actual preparation and full prepared read | 4 / 6 / 6 | 4 / 6 / 6 |
| Sole issuer worker through actual Installed publication | 9 / 11 / 11 | 8 / 10 / 10 |
| Total to Installed | 13 / 17 / 17 | 12 / 16 / 16 |
| Each already-bound full readback request | 3 / 3 / 3 | 2 / 2 / 2 |
| Each pending progress request | previously a full readback | 0 / 0 / 0 |
| Actual C runtime configuration consumption | 2 / 2 / 2 | 2 / 2 / 2 |
| Sealed S factory, sealed C factory, readiness producer, each | 5 / 5 / 5 | 4 / 4 / 4 |

Root's reserve calculation caps Prepare plus progress plus the mandatory complete read at 120 frames, leaving eight frames in that same original Version channel. That arithmetic does not prove other channels fit. The original Root `require_current` implementation was fetched at exact a96 and delegates to synchronous original Registry, Issuer and Root checkpoint work; it does not read remote D/T/B and remains on both sides of each wait request.

The shared SourceBound Training/material channel still has an independently identified 128-frame bottleneck. B's proposed before/after reduction and this progress protocol are necessary changes, not proof that the complete route runs within the original budget. All ordinary qualification counters remain zero.

## Validation and retained limitations

The isolated preformat source overlay has actual mutation checks for exact callers, added unregistered callers, enum privacy, legacy-domain exclusion, complete echo fields, absent-cut refusal, failed-prepare refusal, no owner reads during progress, original counters/cancellation, separate full-readback decoding and the unchanged final physical read order. Logs retain their explicit preformat scope.

Native fixture additions use the actual same-A Version host and real same-process framing with original D/T/B receipts. The original UID-0 issuer case checks Pending, one-way prepare attenuation, then Available followed by a complete read. The cold case checks actual publication withdrawal despite an available scheduling hint. Fixture credentials and same-process admission remain fixtures. These native additions are UNRUN and do not establish ordinary launcher assembly, deployment custody or cold daemon qualification.
