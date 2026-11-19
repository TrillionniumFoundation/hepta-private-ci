# HPCA MEM narrow-budget stratified replay: seed-rotated kind order

**HOLD_NO_GO / DENY_ALL.** This is a shadow-only fairness correction, not a
native Owner, learning, independent-task, retention-benefit, or production qualification.

## Reproduced defect

In the previously implemented select_replay(policy="stratified"), the
per-kind queue always started at fact, followed by episode, skill,
recovery. When all four kinds were available but max_items=1, the selector
always returned a fact regardless of the declared random seed. Consequently
skill/recovery/episode could be **systematically starved** in a budget-limited
replay, while the study called this a stratified replay baseline.

The new seed-versioned deterministic starting rotation gives each kind a
chance to occupy the first slot across distinct seeds while retaining
round-robin traversal and within-kind hash ordering. The code is reproducible
under input permutation and repeated reads. Exact-key RAG and uniform controls
are untouched; sticky tombstone and rights-revocation behavior is untouched.

## Scope and reproduction

- GitHub parent 622b2ad92f79beb072db62cf7905f435b81df5fc;
  parent tree 2d862eefa136a37a1d9d374515b219c93bad0dba.
- Host: HeptaRuntime ai395, Python 3.14.4, synthetic reference records
  with four types fact/episode/skill/recovery and known tombstone versions.
- Narrow-budget test uses 64 declared strings fixed-owner-seed:0..63;
  each one runs the **same** four-entry fixture and a budget of one.
- Unmodified parent: **one of four targeted assertions fails** because
  episode, skill, and recovery never occupy the first slot.
- Patched code: **10/10 relevant tests pass**, comprising six previously
  implemented MEM regression tests and four new focused tests. Red and green
  unittest outputs and local process wall/CPU/RSS measurement are preserved
  in MEM_KIND_ROTATION_EXECUTION.log.
- No additional training, model inference, independent evaluator,
  Agentd/Root Owner attestation or real-task measurements were performed.
  No scientific/production improvement is asserted.

## Remaining caveats and acceptance

This change is a different replay *policy version*; do not compare prior
stratified-run outcomes as though they used the same policy. Declared seed
strings can be selected adversarially, and seed custody is **not** verified;
independent Owner-provided seeds are required for real scientific evaluation.
A single budget-one call cannot cover four kinds; the property here is only
that repeated independently seeded calls do not have hard-coded fact priority.
New tasks/old tasks/deletion-after-cold-recovery must still be evaluated
against exact RAG, uniform, structured, typed and cost-matched strong controls.

Q24 original source/action/feedback time and owner identity, independent
future B, genuine NoUpdate/Adopt-to-different-C, cold daemon/Root recovery,
seven lineage clocks, ACT/CTRL real terminal effects, Core x NDU 2x2 and
full lifecycle resource and failure costs remain **HOLD_NO_GO**.
No permissions changed and no deployment is authorized.
