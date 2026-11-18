# Native historical read budget: independent static review

Status: **STATIC REVIEW ONLY**. No production file, test, source gate, active
owner checkout or runtime was changed by this review. The actual source is
`978719e6137cc1fe9a64bcde7795cd478b2f293e`; evidence-only descendant
`3299c1d3318ff157f4948dee89b7939ef67b515c` preserves the original v13 attempt.

## Measured failure and its exact limit

The original [v13 XML](native-v13/ordinary-whole-cold-no-update.xml), SHA256
`6abdc83dc2a5d044af7868a130cf8826552223efee20275dc6b5f66f60ea15c9`,
records `historical_client.read_limit request_id=65 maximum=64`, then
`historical_client.observe_before_action` and the historical Dataset operation
failure. It also records a complete 19,118-byte Task reply under the 28,933-byte
Task bound. The read-limit refusal is now measured; it was not measured in v11.

The lane sequence is shared across typed historical operations. This does not
prove that every one of the preceding 64 requests was a Task request. The
65th request is rejected before sending its next frame. Separate child logs
provide no total causal order across processes.

## Existing authority mechanism that must remain

`root_historical_task_read_client.rs::with_current_read` performs complete
physical Root observations before and after its callback. Its postcheck still
runs when the action returns an error, and `FenceReadOnDrop` fences exceptional
exits. The receipt compares the complete original image and belongs to the
actual same client/session.

`root_historical_learning_operation.rs` already provides a synchronous,
higher-ranked borrow. Pure repeated checks can use `read_for` inside that
borrow. Keep its trust pointer identity, receipt Arc identity, private
constructor, HRTB, `PhantomData<Rc<()>>`, current signed activation, clock,
error priority and outer postcheck. It must not escape to another thread or
outlive the callback. No dedicated compile-fail escape fixture was found in
the reviewed files; this review does not claim such a test ran.

[Prepared borrowing source](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/978719e6137cc1fe9a64bcde7795cd478b2f293e/codex-rs/hepta-agentd/src/cell_q24_prepared_operation.rs)
adds an actual Prepared-owner identity check on top of the existing Dataset
operation. Returning bytes or equivalent facts does not create that capability.

## Narrow caller opportunities

### Preserve the boundary before witness initialization

[StageFilesData::into_original_inputs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/978719e6137cc1fe9a64bcde7795cd478b2f293e/codex-rs/hepta-agentd/src/production_post_a_q24_owners.rs)
currently makes three standalone Prepared revalidations: before key/journal
descriptor opening, after those openings, and after all witness openings.
Each standalone historical validation opens a new operation with two complete
Task observations, for six Task exchanges at this caller.

The middle operations are not all pure computation. Four signer keys are
opened and read twice; five journal/witness pairs retain permission, inode,
alias and lifecycle checks. After the second validation,
[FileAnchorWitnessStore::open](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/978719e6137cc1fe9a64bcde7795cd478b2f293e/codex-rs/hepta-neuron/src/witness.rs)
can write an initial header and sync it. Recovery takes the original file lock.
Full witness history is subsequently checked.

A conservative candidate would enclose only the first two revalidations and
the intervening key/descriptor opening in the existing Prepared operation,
retaining both calls to `read.require_prepared(&prepared)`. It would return
owned concrete handles, not a borrowed capability. Both Result layers and the
outer complete Root postread must succeed **before any witness initialization
starts**. The third standalone revalidation remains after all witness openings.

That candidate could reduce this caller from six to four Task exchanges.
Combining all three validations into one scope would move an actual physical
fence past the witness write and requires a separate proof; it is not proposed.

### Reuse one operation for profile construction and validation

[CellQ24PreparedLearningV1::root_profile](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/978719e6137cc1fe9a64bcde7795cd478b2f293e/codex-rs/hepta-agentd/src/cell_q24_prepared_learning.rs)
revalidates, constructs a rule/profile, then reaches a second revalidation
through `require_profile` → `require_initial`. The intervening rule and profile
work is pure for this source.

A private `require_profile_in_operation` and
`require_initial_in_operation` could pass the same actual Prepared borrow
through both checks. Keep every binding, frozen-scope, initial/scope equality,
current signed activation and deadline check. Calling the standalone wrapper
from inside the new helper would re-open the original physical operation and
lose the intended change.

This could reduce four Task exchanges to two for this caller. Together the
two proposals could save four Task exchanges per invocation of those two
callers. That is a static count, **not proof that the complete workflow fits
within 64 shared-lane requests**.

## Existing controls to preserve and execute on any new candidate

- `cell_q24_training_source_operation_tests` checks a different actual source
  Arc despite identical encoded data, the accepted original clone,
  cancellation, and withdrawal that cannot be hidden by returning Ok.
- `cell_q24_source_receipt_operation_tests` checks another actual Prepared
  owner and withdrawal before read/outer completion.
- `cell_q24_training_stage_operation_tests` retains lane reentry refusal and
  withdrawal before releasing the owner.
- `production_post_a_q24_owners_tests` and
  `production_initial_q24_files_tests` retain key/lifecycle/permission/
  hardlink/alias failures and the requirement not to initialize a witness when
  those inputs fail.
- Original historical-source mutation, recovery and failed-postcheck controls
  must still validate the actual deployed Root/receipt path. Component Dataset
  controls alone are not evidence of that deployment.

These are locations of existing controls, not test results produced by this
review. The SGD step and the already-scoped freeze owner do not open the
repeated Root operations identified above and should not be changed for this
hypothesis. Any implemented candidate needs its own source freeze, original
source/caller gates, negative controls and complete native NoUpdate/Adopt
execution. Do not reset the sequence, delete revalidation, substitute old
binary/results, or infer adoption from a component pass.
