# B comparison objective separation — isolated candidate

Status: prepared source only. No Rust formatting, compilation, test, source gate, H execution, commit, ref or active source change was performed for this package. The existing published source remains cc57c7198db6293ccca562253c42fffbe2a04633. Real useful task-chain results remain zero / Unknown.

## Purpose and scope

This package changes three existing `*_tests.rs` files. It separates the four complete comparison-objective fields consumed by the original B fixture from the opaque A Source publication. It does not construct an A Source publication, a new authenticated RunStart, a Training owner or Root authority from the borrowed fields.

The before images are the exact Root 86-file overlay identified by `3f7d40d4933669da33d2aef3491efb431c5771ae`. These three files are unaffected by the later Pending/expiry and A/Material-to-Trainer layers, so Root can require these exact before identities when combining the new candidate. The prior layers remain immutable.

## Interfaces

`BorrowedOriginalObjective` borrows the objective digest, complete semantic bytes, objective-function digest and complete function bytes. Its explicit preheld constructor checks the original RunStart bounds of 1–262144 bytes per byte field and exact byte digests. These checks establish consistency only. The caller must already hold the full trusted comparison contract; a child report cannot select that contract or its authority.

The original `BFixture::populate_from_original_training` still accepts the original Source publication and delegates once using its complete original record. The B population loop preserves its independent admissions, run IDs, times, original Source/Cell writes, signed Decision/Outcome calls, original seven-source structure and assertions. Only the source of those four objective fields changes. Existing old callers require no API change.

`CompletedTrainingInputs::from_original_completion` retains every original input/history, D/T/Candidate, role, cut and manifest assertion. Its stored Source reference is projected into a borrowed view after those checks. The new `from_preheld_objective_and_original_completion` accepts a preheld Source input, expected A history and original task configuration separately. It first authenticates the opaque original D against the entire original Material configuration. The expected A history must be nonzero and equal the history in that authenticated D snapshot. Source principal/agent/cell/run/objective, full task digest, Source frontier and generation scope must agree with the preheld contract. The original actual T/Candidate equality, denied authority, three-cut progression and complete baseline/candidate manifest checks remain.

The new constructor does not prove that its caller obtained the preheld data before child launch. That ordering and the original signatures are obligations of the separate first-admission path. Nor does this package provide the missing production Root CURRENT, Artifact/control/Original-A custody or a full three-UID deployment.

## Mechanism test and preservation

The two existing Fresh stage test methods are a byte-identical prefix. One new unexecuted method uses the existing Fresh E→D→T→Candidate fixture, accepts both the old and separated input constructors, and rejects a different A history, different Source run, changed complete Source input, rewritten Material history and changed objective-function bytes. The new case uses Result-based assertions and always passes its result to the existing `finish_case` cleanup. It does not run B/E a second time or claim independent external measurements, parent-before-child preholding or deployed authorization.

Pure verification performed: every local pre/post size, SHA-256 and Git blob identity; exact inverse transformations; forward `git apply --check` and application plus reverse application in a throw-away directory; exact old constructor body after the single stored-field projection; unchanged original B assertion/Decision/Outcome call counts; unchanged two old test-method bodies. These are byte and source checks, not Rust test results.

## Source grounding

- The original four-field use and Current/UID limitations were independently audited in `50a182e905aca1e388bafe4dffe28277a7c568d9`.
- Original B source fixture: `9528b169dd57d71dd30d087d8732eeaec90c6d02`.
- Original Fresh B input facade: `6c3438d982449daf16e5ed3aec829f3b616a3ff3`.
- Existing Fresh tests: `a1f5cfd587e3472b2f9f4b2417dd6b151dd92d6e`.
- Original RunStart record and bounds: `cb387137df02044221c2b2caa0bc8db0ccde3fd7`.
- Original generation scope/config types: `11cde7b9f16322905d106fb8107846b27592b9d1` and `085bcfd745c7a06426d90e5ee881d04694238ff7`, fetched from exact cc57. Both expose the compared fields; the scope derives Eq/PartialEq.

`SOURCE_PACKET.json` carries complete before/after text and identities. `SOURCE_DELTA.patch` is its exact diff. `STATIC_PRESERVATION.json` and `BYTE_PATCH_REVIEW.json` distinguish the performed pure checks from all unperformed execution. Root remains the sole integrator and executor authorization owner.
