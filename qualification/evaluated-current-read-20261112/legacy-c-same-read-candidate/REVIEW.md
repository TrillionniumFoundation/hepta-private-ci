# Same-call published CURRENT candidate

## Identity and actual failure

- Base: `edaf1d9a420dc99336f36b24515eb9c65a97b0da`.
- Bare code tree: `ec949496b0fdb728ad830ad61e541ba080e3391c`; 11 changed paths.
- State: STATIC ONLY; no ref, commit, job or actor has been created by this candidate.
- The preserved original failure tail is `48c873e78aa594816c87537a45c7188ffdf577ea`, 17,726 bytes, SHA256 `33ae5710943289558cd68373101e6f4d2723c9d692d490f6c28a79ee8faad135`.
- The actual legacy C callback began after 339.662 microseconds, returned 1,007 bytes with no callback error after 707.475092 ms, and the exchange failed at 707.83391 ms with DeadlineElapsed.
- The deadline remains 500 ms. The original failing method and all existing assertions remain unchanged.

## Narrow implementation

`PublishedCircuitCellOwnerV1::read_learning_next_use_set` executes the original native NextUse body, including original Selection equality, actual Source publication before/after, committed Cell identity/checkpoint, and final task CURRENT.
Its private owned result contains the Selection, NextUse observation and actual Source publication digest produced by that one read.
The type has private fields, no Clone/decoder and no constructor accepting caller data.
The old public NextUse method delegates and returns only its original observation.

The CURRENT service consumes that result during the same no-effect call.
Its actual task CURRENT and exact Source-input/current checks bracket the native reads, and it independently reads the original Selection again before the final Source/task checks.
The inner native read already compares both full Source publications; the service no longer repeats the same publication pair around that same operation.
The Source journal forbids replacement of completed bytes for a key, and final require_original_input reads the same physical witness/current and withdrawal state.
No saved observation is accepted in place of current owner evidence on a later call.

No Observer/Selector evidence read is removed.
Request purpose, context, actor, operation, nonce, receipt digest, signature validation, bounded channel, clock/lifetime, role separation and wire shape are unchanged.
No journal write, claim, CAS, owner construction or effect is introduced in production.

## Static call accounting

| Per actual published CURRENT request | Original explicit task CURRENT calls | Candidate |
| --- | ---: | ---: |
| Selection | 10 | 6 |
| NextUse | 15 | 9 |

One legacy C evidence callback still reads T six times, S evidence twice, C CURRENT twice and S CURRENT four times.
This yields 70 versus 42 explicit task.require_current calls in the inspected graph.
These are static source counts, excluding nested Trainer/Material work and internal filesystem operations.
They are neither elapsed-time measurements nor a full shared-Material budget proof.
The evaluated S PredecessorUnavailable failures and full bridge's recursive Material budget remain separate open issues.

## Real negative test and exact source guards

The new native test uses SelectionFixture, the actual original Selector attestation, ordinary C execution and the original CURRENT service.
A first read must equal the native public NextUse observation and actual Source publication digest while preserving original owner bytes.
A cfg(test)-only hook then truncates that same Source journal only after the next native observation has completed.
The call must fail, the actual file must have length zero, the original channel must be unavailable thereafter, and the server must report an error.
The six old native methods remain; this module has seven methods in the candidate.
This new method has NOT RUN.

The original public NextUse boundary loses only the service caller; its two original receipt-owner callers remain.
The new private read-set boundary has exactly one external product caller, the CURRENT service.
The original checker intentionally excludes calls in the definition file; the public delegating wrapper therefore has an exact whole-body code guard.
The complete native helper's source/Cell/order checks and consuming result extraction are guarded.
The Source-input guard is moved to its new private helper, preserving all exact scope checks; constructor bracketing remains intact.
The service's complete private field layout still has an exact code guard after the original cfg(test) mask, including the blanked test-only field.
No checker or general allowlist rule changes. The sole active CALLERS pin is replaced by the exact new bytes.

Five existing QA files follow their actual moved implementation/caller tuple; no original rejection property is dropped.
One source mutation method is added, bringing original_published_read from eight to nine.
The new method rejects removal of native cut/Selection/Source/Cell/tail checks and of consuming any read-set component.
The remaining QA method counts are unchanged.

## Remaining execution gates

1. Original scoped formatter and source mutation/caller checks on the combined exact source.
2. Real native compilation and the full existing methods, including the old C timeout method and the new same-Source truncation method.
3. Confirm unchanged physical Source/Selection withdrawal rejection and exact original request/receipt identity.
4. Observe actual callback duration under the unchanged 500 ms limit; no success is inferred from static counts.

All 11 Git postimages were read back in full and checked against Git identity, SHA256 and original prepared text.
That verifies transfer only; formatter, compiler, source gates and native execution remain NOT_RUN.
