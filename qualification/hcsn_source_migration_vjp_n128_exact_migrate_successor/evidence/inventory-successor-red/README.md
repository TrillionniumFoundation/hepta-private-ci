# Draft #6270 immutable RED evidence

This evidence-only package preserves the exact GitHub Actions artifact from
run `43285117987`, job `131416350055`, source
`ec608133a275a97f6712561a08af218fee4ebe26`.

The sole bounded child exited without `RESULT.json`. The original stderr shows
that `freeze_n128_problem` read `model.spatial.grading`, while the frozen
`GradedSpatialGenerator` dataclass exposes the same parameter as `stretch`.
The wrapper therefore recorded
`UNKNOWN_TERMINAL_NO_RESULT_NO_READMISSION`. The unique execution key is burned
and is not rerun by this evidence publication.

`originals.zip` is byte-for-byte the downloaded Actions artifact. `AUDIT.json`
records its archive SHA-256, all eight member hashes, the original cost, the
zero recorded forward/adjoint/optimizer counters, and the retained HOLD state.
This package performs no model import, migration, forward, adjoint, backward,
optimizer update, scientific qualification, or production adoption.
