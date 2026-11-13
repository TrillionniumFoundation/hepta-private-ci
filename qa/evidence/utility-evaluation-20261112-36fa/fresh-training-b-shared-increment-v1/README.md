# Shared original Trainer for the two B members

**HOLD: test-only, unformatted, uncompiled and unexecuted.** This is an isolated three-file increment over the frozen Fresh T→B component and the separate completion-observer increment. Neither input directory nor cc57 is modified. The exact layered identities are in `MANIFEST.json` and the complete before/after images in `SOURCE_PACKET.json`.

The production type `OriginalCellEvaluationPanelMemberOwnersV1` already accepts `Arc<LearningIterationEvidenceClientV1>`. Its panel reads primary then retention sequentially, with fresh actual Trainer reads inside both. This increment lets the test facade use that existing interface without manufacturing a second original Trainer connection.

## Added interfaces

- `PreparedBPanel::complete_with_shared_original_trainer(input, Arc<LearningIterationEvidenceClientV1>)` gives the same Arc to both real B members. Existing `complete(input, primary_value, retention_value)` remains available and delegates with two independent Arcs, preserving its previous behavior.
- `PanelMemberFixture::complete_from_shared_original_trainer(..., Arc<...>)` passes the actual shared read-only client into the unchanged Qualification and Member construction. Its old by-value entry creates one Arc and delegates. The old legacy fixture still constructs its original peer and joins it as before.
- `OriginalTrainingPeers::new_shared` constructs exactly two real fixture sessions: Candidate and one evidence-only Trainer. `take_shared_trainer()` consumes the one initial read-only connection. `finish_shared()` shuts down and joins both actual handlers and returns their actual two counts. The old three-session constructor, take methods, `finish()` and Drop implementation remain byte-for-byte unchanged.

The caller creates the read-only connection before D/T, then binds it once to the actual opaque Dataset and Training results using the existing `bind_original_training`. It wraps that actual client in Arc and supplies it to the new shared B entry. The two B tasks still use separate data/Cell/execution/Qualification owners and retain their original honest Ineligible assertion. No task, result, signature or permission is replaced by sharing a reference to their common original T predecessor.

## Teardown and resource limits

Close all external E/Version/other consumers and finish `CompletedBPanel` before normal `finish_shared()`. Drop/error teardown closes the actual streams and joins the owned server threads. It does not cancel a previously admitted remote operation or create successful handler counts. Any original error is returned; joining still depends on the existing bounded handlers.

There is one physical evidence channel, one request counter, one retained complete signature, one peer/pidfd identity and one original lifetime. Its 128-request limit is aggregate across both B tasks. Concurrent use is not added; original panel reads remain sequential. No fresh Execute capability is cloned. The separate Candidate channel retains its own purpose and original limits.

These private test transports call the actual original handlers through existing cfg(test) adapters. They do not perform the public cross-UID/permit admission, so this change is **not proof that the complete public ten-owner route fits four permits**. The separate capacity report (`0d5ce94fcd6654e5124ef7acee94c9369e5a95d0`) explains why the other retained Version/S/C command clients still require a distinct design review. No production limit, timeout, signature window, verifier, source guard, assertion, threshold or contract changed here.

## Static preservation

The preparation script verifies all three exact input Git identities, writes only a new directory, records every explicit replacement, and inversely restores the complete first two inputs from their postimages. The ports increment is append-only after the completion observer. This is textual preservation, not a Rust compile or a runtime test. The two preexisting by-value entrypoints now allocate their Arc before delegating; that is a test-only allocation move, with all original real-owner work and assertions retained. The combined candidate still needs its actual format, compile, regression and public transport validation.
