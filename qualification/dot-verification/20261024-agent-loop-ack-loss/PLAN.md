# Frozen local diagnostic plan

Source: d282d937aab7cf1ba3a1751db72f337442d54078. Use its real native loop with controlled test-only file snapshot owners; no sockets or providers.

Six cases, fixed before execution:
1. ModelCompleted snapshot saved, reply lost: cold reconstruction resumes Tools; total unique model dispatches 2, effect dispatches 1.
2. ToolCompleted snapshot saved, reply lost: resumes next Model; unique model dispatches 2, effect dispatches 1.
3. CancelRequested snapshot saved, reply lost before notifying owners: reconstruction calls both cancel owners once; no model/effect dispatch; Cancelled terminal.
4. Cancelled snapshot saved, reply lost after both ACKs: reconstruction returns stored Cancelled without another cancel request; both cancellation counters remain 1.
5. ToolCompleted fails BEFORE snapshot write, with independent effect receipt persisted: old Tools cursor observed again, same operation key twice, two effect-owner observations but only one execution. This deduplication is explicitly the EffectOwner fixture guarantee, not a loop-provided capability.
6. Negative contrast to case5: deliberately contract-violating effect fixture discards receipt, keeping only an independent execution counter. Same operation key is observed twice and causes TWO executions. Expected outcome is diagnostic confirmation that the loop alone does not provide durable effect deduplication.

Store context cursor, effect receipt, effect invocation keys, execution counts, inference receipt IDs and cancellation counts in independent files. Fixture persists a restricted deterministic frame shape, not arbitrary product conversations or full provider-native continuations. Drop all three adapters and reconstruct from files; no in-memory frame/receipt carryover. This is process-local object reconstruction, NOT SIGKILL, physical power loss, filesystem atomicity acceptance, durable product owner integration or permission to execute real effects. Do not amend expected counts after seeing outcomes.
