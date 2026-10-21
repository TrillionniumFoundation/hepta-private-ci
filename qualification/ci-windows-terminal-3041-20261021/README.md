# Original Windows qualification for continuation 3041

The original Windows private-state workflow passed on source
`52293403ea1e06465c41d24d39b54959bad40936`, tree
`8944830c3b3ed494987d01ef631ab48b69e75d1c`. This is the original job
[119193228150](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39591475745/job/119193228150),
which ran from 11:54:55 to 12:06:37 UTC on 2026-10-21. No job was rerun or
cancelled to obtain this result.

The complete connector-decoded log is preserved as UTF-8 without rewriting its
BOM or line endings, losslessly compressed with XZ. The JSON receipt records
both raw and compressed sizes and SHA-256 digests. Warnings in the original log
remain present.

## Native coverage

The five original `just test` selections ran 30 tests: 12 private-path tests,
2 Prompt Registry tests, 3 signed-store tests, 2 authority-lease tests, and
11 Agentd Prompt Runtime tests. All 30 passed. Nextest's other skipped counts
refer to tests outside these original selections; this is not a full-workspace
Windows test claim. The original Python acquisition harness also ran 6 tests
and passed.

The separate acquisition probe then ran the original positive source and two
isolated counterfactuals. The positive source rejected ancestor substitution
and rejected a junction before creating a private leaf. The unchecked-create
counterfactual failed only the creation assertion and recorded `created=true`.
The path-check-open counterfactual failed only the substitution assertion and
recorded `redirected=true`. Both counterfactuals returned the expected failure
status, and the harness restored the original production source.

## Original artifact integrity

Artifact `12344560809` is preserved as `windows-private-state-52293403.zip`.
Its 13,136 bytes have SHA-256
`5dd4f22d8f6520b8dfcbcee304c8c51cb64cef6aa2e3dca69ea6a29bb5a1cbcf`,
matching both the original upload log and the Actions artifact API. ZIP CRCs,
all nine member byte hashes, all three lane source and log hashes, and both
counterfactual patch hashes were checked against the original manifest.

`native-controls-verification.json` records the original manifest's exact source
identity, observations, test statuses, `qualified=true`, and `restored=true`.
This result covers the source above. The later Bao, Memory, state and immutable
reader changes still require their own native Windows qualification.
