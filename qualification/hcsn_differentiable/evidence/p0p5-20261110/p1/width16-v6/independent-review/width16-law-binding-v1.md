# Independent width16 state and finite-law binding review

**All five source/input linkage checks pass. Scientific admission remains HOLD.**
The [receipt](width16-law-binding-v1.json) and [exact script](review_width16_law_binding_v1.py)
independently check the frozen width16 wrapper, checkpoint, traces and all five
planned finite-continuation inputs. This review takes 0.377452 seconds and does
not repeat any slow high-precision oracle or train another model.

The plan's 34 Python files agree with the copied source and export receipt.
The after-checkpoint is the real result of two full 256-event Adam updates on
A01-0, with optimizer state counters equal to two and unchanged common
frontend/head and physical tensors. Its file identity is distinct from both
its whole-wrapper tensor identity and its inner-network tensor identity.

The 512 original training visits belong to the two forwards **before** optimizer
updates 1 and 2 (`update_index` 0 and 1). The separately exported 768 visits are
three complete A-episode evaluations of the final checkpoint (`update_index` 2).
Those evaluations pass through the actual common frontend, HCSN wrapper and
head; a forward hook observes the same network result that the core recorder
captures. They must not be added to the count of states actually visited during
optimization. All three data files match the official prepared manifest, have
valid localization observation masks, and belong to A training partitions.

Every saved starting-law tensor equals the matching recorder posterior exactly.
Its physical parameters, grid and operator configuration agree. Its future
duration list equals the exact next-duration slice from its original episode.
The five fixtures are A01-0 position31 with 32/128 intervals, A01-256 position127
with32 intervals, and A04-3072 position47 with8/32 intervals. The finite oracle
receives these laws and durations, without future observations or labels.

At this review snapshot, the original 512-state pressure audit is passed, while
the final-checkpoint A04 pressure audit is HOLD. The retained long128 and two
burst finite stages each report passed_fixture. These are different numerical
questions, and all original stage results remain untouched. Other planned
stages were still being evaluated and receive no result credit from this note.

The runner deliberately permits a completed stage with a numerical HOLD.
Consequently `completed` or process exit0 establishes only execution completion.
A qualification summary must also inspect `audit_status` / `fixture_status`,
coverage, truncation and source-before/source-after identities. The numerical
owner confirmed that the final aggregate does this. Selected-law success does
not establish whole-training accuracy, sufficient training or task benefit.
