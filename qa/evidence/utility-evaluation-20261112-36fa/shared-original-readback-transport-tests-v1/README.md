# Shared original readback transport tests — isolated preparation

This packet adds two test-only Rust files and four concrete tests for the sealed published Version readback bundle. It targets the independently stored production proposal `92a1567ac32c886d9d7386fb80915071475528bf` over exact cc57. It does not change production code, the active checkout, refs, test budgets or connection limits.

The candidate is **not formatted, compiled or executed**. Git source blobs and metadata have full-byte readback proofs. Those proofs establish artifact identity, not passing tests.

## Files and integration

- `cell_q24_training_shared_readback_test_support.rs` supplies an observer and a one-shot scheduling pause around the actual original Trainer command handler. The handler generates every response; the helper forwards its bytes unchanged.
- `circuit_evaluated_version_shared_readback_tests.rs` constructs the existing real publication/recovery fixture, exports through the production Published/current checks, and owns cleanup of the resulting D/T/E peers and C.

Ordinary is the sole integrator for the two parent-module mounts and its three narrow cfg(test) bundle methods. `MOUNT_AND_HOOK_CONTRACT.json` fixes the exact required signatures and reference parent pins. The packet contains only the two new files; it must not overwrite a parent file that already contains other reviewed test additions. In particular, the original command-support completion observer and ordinary's separate export-refusal tests remain.

The three hooks are: actual T readback; equality of the two T/E Arc identities; and a read-only observation of the original T slot's next request id. They expose no client, stream, descriptor, execution operation, counter setter or deadline setter. The actual readback hook advances the real client's state through its unchanged implementation.

## Four actual mechanisms encoded

1. **Alias competition:** after the real T owner produces its response, hold that response before transmission. A second public bundle read must contain the original Trainer Unavailable error. Exactly one real T frame was observed. Release the original response; the winner and a later read from the other alias complete normally.
2. **Cancellation:** abort and await cancellation of a public bundle read while its actual T exchange is waiting for that response. Existing aliases and a new clone must all observe the consumed slot before and after release. A separate control read of the same actual T owner still returns the full original receipt and signature; it is never substituted into the failed bundle.
3. **The original 128-request budget:** use the existing `commands::serve`, which calls the unchanged production `serve_command_channel`. Observe the actual number already spent by Version admission, alternate aliases until real request 128, and require the original request-129 CommitUncertain followed by Unavailable/None for every alias. The original server must terminate with its original Unavailable. The controlled helper's copied loop is not used for this test.
4. **Absolute deadline:** supply a legal shorter ten-second lifetime to the existing recovered-connection factory before binding or sharing. Wait past an upper bound recorded only after both original endpoints have been constructed. A later clone retains the same clients and request id; its first expired request must be CommitUncertain and all aliases must subsequently have no channel. The same T owner remains readable through an independent control.

The last two tests use a T-only test method. Repeating full T/E reads 128 times would exhaust the older B-member evidence fixture's separate 64-frame transport first; changing that limit would make this a different test. E's separate cancellation/exhaustion is not claimed.

## Original behavior and evidence

The T client removes its channel from the one shared slot before awaiting its blocking request. It restores the original channel only after complete request/response, peer and signature validation. An overlapping call sees None. Cancelling that awaiting task cannot restore a later blocking result. Transport request errors map to the original CommitUncertain, and the already consumed slot then yields Unavailable. These are the existing client conditions exercised here; the test does not add a queue, retry or reconstructed channel.

The real service retains its 128-frame loop. The connection factory retains its actual peer/pidfd checks and unextended deadline. The shared bundle retains both original clients. The public bundle path checks actual T then actual E, comparing complete original results. Error assertions inspect the original typed error chain, not error-message strings.

All tests compare original publication/predecessor/B/E journal bytes and require C's original revision to remain zero. Their setup uses the pre-existing PublicationFixture, which already performs actual T and actual Ineligible/NoUpdate publication with its enrolled test credentials and B-member fixture peers. It is a cold recovery/readback mechanism fixture. It does not represent Fresh Root, a real independent B evaluation, public ten-owner admission, a four-slot deployment result, or a real utility outcome.

## Cleanup and limitations

Normal and Result-error cleanup releases the pause, drops all owned clients, joins every D/T/E peer even after an expected T error, stops the actual C and finishes the publication fixture. A Drop fallback releases the pause and joins those three peer threads during unwinding; it does not claim asynchronous C/fixture cleanup during panic. A five-second scheduling-latch bound fails the test if reached; it does not extend or replace the original protocol or test deadlines.

The original 8 MiB stack and 60-second test budget remain unchanged. Neither fixture construction nor 128 actual native readbacks has been timed for this proposal. The ten-second expiry setup may fail if cold admission itself takes too long; such a failure must be kept, not repaired by increasing a limit. Exact whole-repository module visibility, combined afterimages, formatter output, type checking, caller/protection registration and actual final test inventory remain integration gates.

The earlier test draft `0ef2ef2e34938f662a233ae67478b9f85a6d07b1` remains immutable. Its budget case used the controlled helper loop. The final file `30769dda72e5fe509bed1e1c8ce251f79f1861d2` uses the original service for budget and expiry; the exact 15 replacements reverse to the entire earlier draft byte-for-byte. That is a static correction, not a test failure or test result.

## Storage and execution facts

Both final source files, the complete source packet, patch, mount contract and static review are independent Git blobs with full UTF-8 byte readback. No current local file is claimed: this preparation was completed through V8 and Git while the previous workspace was unavailable. No H request, Cargo, Rust parser, formatter, test, source mutation, ref update or qualification verdict was performed for this packet.
