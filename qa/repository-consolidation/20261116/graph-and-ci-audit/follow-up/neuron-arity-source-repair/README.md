# Neuron arity repair: original native validation

This evidence records the reviewed four-file parameter refactor on the exact
local dependency closure from commit
`eeefbc864e6a254e9085d542c1e6c3647e1c881d`. It preserves the existing framed
digest byte protocol and all existing tests, with three new compatibility
regressions. It does not qualify the complete c2d family or Windows execution.

All nine stages passed without changing any of the 13,706 recorded inputs:
the original formatting recipe, an explicit four-file formatting check, the
original scoped fix recipe, the original temporal strict Clippy command, both
original regression group builders with strict Clippy, the original helper
build and verification, and the complete original Neuron package.

The complete package ran 399 tests with no failure or skip: 374 library tests,
11 near-matched binary tests, six mechanism-probe binary tests, and eight
trained binary tests. This scope is the earlier 396 tests plus the three new
compatibility regressions. The isolated group builders retain their original
generated lockfiles; their results do not replace whole-workspace validation.

The original hosted failures, source proposal, and materialization plans are
retained inside the original source kits. The 34 top-level originals also
preserve every native invocation, receipt, log, both input maps, JUnit report,
the verified helper executable and its Cargo artifact records.

## Restore and verify

Decompress `manifest.json.gz` to obtain the immutable manifest. For each
ordered entry in its `parts` array, verify the carrier SHA256, decompress that
one carrier, and verify the decoded fragment SHA256. Concatenate the decoded
fragments in the recorded order to restore the original gzip archive. Verify
the archive SHA256, decompress it, then verify every tar member against its
original length, SHA256, and Git blob identifier before writing it.

Every physical carrier is an independent gzip file below 500,000 bytes.
Restoration of all 34 original files was verified on both hosts. No timeout,
stack setting, test assertion, retry policy, feature, or production authority
rule was relaxed.
