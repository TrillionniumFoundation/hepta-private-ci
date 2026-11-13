# Root-local generation custody: exact API review

This independent review identifies a complete local unit that can be implemented using the original publication and Q24 task factory. It is anchored to source `0c59aaca0b4932507f068c723f73da2f96729b3d`, tree `4b1ef6a81f8fc49d4c267d9e47bc4b8127fc8d09`. No new coordinator implementation was frozen at this review's cutoff.

The original path already supplies the required custody chain: consuming Prepared publication creates Ready with the original journal and concrete LiveCurrent; consuming Ready creates a sealed PublishedTask; the existing Q24 factory opens the Cell from that same task and installs its private writer. The factory returns the actual Source and Cell readback owners. A coordinator can retain its task clone and these returned owners, then delegate retirement to the original same-Arc, three-Source-read, actual-Cell-commit and durable-drain checks.

The initial Prepared factory creates Current internally and exposes no public owner getter. A constrained same-module or child-module constructor is needed to retain the same concrete Current for operation readback. The update path already receives that Current as an input. Neither case requires a new authority, a generic production store, a parallel Cell, a public callback, or a forged completion.

Publication consumes its receiver and may fail after protected CAS. A failure result can retain the original Current, operation ID and intent digest for the existing readback API. Observing Prepared is not permission to re-dispatch; observing Published is not sufficient to construct Ready without the original recovery and live-owner checks. The original Artifact lock must be released before LiveCurrent construction reacquires Artifact, selected payload and FinalUse in their existing order.

`FROZEN_SOURCE_VERIFICATION.json` records 19 exact source files and three fresh complete Git GETs. The previously reviewed `circuit_feature_current.rs` differs from actual 0c59 only by two already integrated exports; inverse byte equality is recorded. `verify_frozen_inputs.py` performs only source-byte and identity checks. It does not import candidate code or run Rust, formatter, QA, H, Git commands, a gate or a production main.

The detailed signatures, ownership, failure semantics, private visibility and patch-review conditions are in `REVIEW.json`. This is implementation guidance, not an approval of a future patch or a native qualification result. Cross-UID CURRENT transport, external FinalUse issuance, ordinary RunStart, fresh three-UID orchestration and real utility remain outside this first local unit.

All paths in the placement are relative to the current evidence leaf. The source and evidence refs are not modified by this review.
