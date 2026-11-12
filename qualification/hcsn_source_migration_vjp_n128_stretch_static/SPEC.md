# Visit-897 N128 `stretch` field static repair

Global status: **HOLD / NoUpdate / all_closed=false**.

Draft #6270 is an immutable terminal RED/UNKNOWN record. Its sole key is burned.
The bounded child reached source-migration setup and then failed because
`freeze_n128_problem` read `model.spatial.grading`, while the frozen
`GradedSpatialGenerator` dataclass exposes `stretch` and uses it directly in
the node formula.

This separate successor changes that one field access to `stretch` and performs
only a zero-import, zero-numerical static review. The exact equality
`model.spatial.stretch != 6.0` remains fail-closed. No alias is added, and no
geometry, node formula, rates, physics, delay, support, input, threshold,
denominator, call cap, or resource gate is changed.

The reviewer must establish all of the following from repository bytes and the
Git diff against exact parent `ec608133a275a97f6712561a08af218fee4ebe26`:

1. the scientific-code diff is exactly one removed `grading` access and one
   added `stretch` access in `large_adjoint.py`;
2. the frozen dataclass has a `stretch` field with default `6.0`, has no
   `grading` field, and its `nodes` formula still consumes `self.stretch`;
3. the original spatial source SHA-256 remains
   `ad6b6865374d1f7f6ed493d6485a60be9f39795d1eb232e681f32a020f5b50f0`;
4. all nine predecessor RED/UNKNOWN records, including #6270's artifact and
   post-migration-setup failure, remain explicit and are not upgraded;
5. candidate imports, model forwards, adjoints, backward attempts, and optimizer
   updates are all exactly zero.

This stage has no numerical identity and cannot authorize numerical work. A
later N128 attempt, if any, requires another separately frozen source and key.
It does not establish N128 VJP correctness, N512 scalability, full-prior or
fullnetwork AD, finite-domain qualification, task benefit, HPCA benefit,
external custody, production adoption, or global closure.
