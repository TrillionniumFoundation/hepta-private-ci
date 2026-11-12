# Independent Model / Root carrier source review

Date: 2026-11-12. Reviewer: `learn_evaluator_budget`.

## Exact scope and evidence limit

Reviewed production source: `988ec9c67d745ea0fef3bf297321f089d75af11b`, tree `d0d22411f5cec8df73d99730679086b782001eeb`, parent `cb9f05509928e8f45368a550af5dd82396460be5`. The subsequent real two-parent merge `97a40c2965e908988318a0a4fcf42c1239dcb52f` has no production Rust diff from 988. `source-988-manifest.json` records the exact Git blob and SHA-256 of the 15 files directly inspected.

This is an independent read-only source review. No Rust tool, H harness, native test, fmt gate, full caller proof, or ordinary A/B/C experiment was run for this review. The 51 successful source QA methods on the separate fixed E source `993f9543560db93e051d0170b80ee57314c64ceb` are not qualification of this Model source or any later fix. The ordinary positive adoption, complete ordinary NoUpdate/fallback and real daemon plus Root cold-restart counters remain zero.

## Carrier observations

The review found no additional carrier bypass in the inspected 988 changes:

1. `CandidateOriginalOperation::begin` actually reads the common Experience/Dataset/Training prefix. `close` reads it again and compares the complete original Dataset receipt, Training receipt and first three signed evidence pairs. These are original owner reads through `Continuation::read_stage`, not retrieval of stored CURRENT. The private lifetime-bound operation retains its actual owner reference and failure guard; `require_owner` checks pointer identity.
2. The outer Evaluation path keeps actual Candidate reads around the original Evaluator operation. The outer Model path obtains an actual Evaluator read before and after Model work and compares the complete E receipt. After closing the actual common prefix, it reads original Model CURRENT again and compares the complete Model receipt, complete Evaluation prefix and DENY_ALL posture.
3. Model host `original_inputs` obtains actual Dataset and Training observations on each response. Its Arc is the same previously consumed material client; it neither reconnects nor renews the deadline. The staged E carrier borrows that client, removes its sole channel, performs actual Begin/Pages, and can release material only by consuming its actual Finish. A dropped or failed unfinished transfer does not restore that channel.
4. `current_after` consumes Finish before re-entering the original Trainer lane for the last Model journal read. `Context::authenticate` itself obtains a fresh clock after original material/Dataset authentication, and material/full Model-input validation follows the last Model read. Remote E network work stays outside the original Trainer lane.
5. The Ineligible branch performs actual Finish and complete binding/E comparison before returning Ineligible. The material codec, panel validation and material verification retain nonempty retention membership and actual independent B/retention proof checks. Local transfer reuse does not upgrade qualification or supply a Model/adoption claim.
6. The opaque Candidate evidence is neither Clone nor serialized or stored on an owner. Failure/drop preserves the failed operation guard. Root consumes it once under the same concrete owner after its own read, and authenticates all original signatures and optional original Model record. Independent Root readback calls start a new actual owner operation; the final Root readback compares the entire snapshot and pending status before fresh verification.

## Confirmed pre-existing checkpoint timing gap

At 988, `authority_host_learning_resident_runtime.rs::continue_original` does its final `owner.read` at line 357, verifies complete evidence at line 364, and then awaits `gate.checkpoint` at line 372. `authority_host_learning_resident_gate.rs::checkpoint` discards the actual post-CAS timestamp returned by its original authority boundary. `ResidentRootAuthorityV3::perform` validates grant/lease authorization after the CAS, but does not validate the role-evidence signatures there.

Consequently, an earliest Observer/Evaluator signature can be valid at the pre-CAS verification and expire during the checkpoint durability operation. The durable successor may still be recorded and the runtime may reach its next loop iteration without post-CAS role-evidence authentication. This gap predates the reviewed carrier change; it was not introduced by 988.

The independent outward readback path is narrower: runtime lines 270–283 perform the final actual Root read and then verify all full evidence at that returned clock. That path rejects expired evidence. This review did not find an outward stale CURRENT leak and does not claim one. The confirmed gap concerns continuation checkpoint advancement itself.

Root explicitly accepted the gap into this round. Model owner is implementing a separate fix that preserves the actual post-CAS clock and revalidates the complete evidence before another loop iteration. Any post-CAS validation failure must return CommitUncertain, retain the already durable bytes, and drop the continuation. A separate explicit Root mechanism fixture will exercise expiry across the actual CAS boundary. Neither the proposed fix nor that fixture inherits the 988 review or the 993 source-QA result; their exact new source requires separate recording and validation.

## Other acceptance boundaries

At this source, `ResidentOriginalStageOwnersV3::require_stage` still explicitly rejects Candidate Selection and NextUse with "original Candidate selection and adoption route is absent". This is a visible existing integration gap, not a new carrier defect. The reviewed transfer optimization and source mechanisms do not prove a positive ordinary adoption, a fully integrated fallback, persistent private state, or a real daemon/Root cold restart.
