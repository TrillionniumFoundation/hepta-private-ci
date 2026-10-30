# Original system-safety execution records

This directory retains immutable local execution output and source bindings for
the provider-effect changes in PR #4332. It is an audit attachment, not a new
development plan, operation owner, evidence registry, qualification profile or
production acceptance decision.

`local-executions.json` indexes the original JSON and log members in
`local-executions.tar.gz`, including their SHA-256 hashes. All 39 completed
executions available when this archive was assembled are retained. They include
the original late-acknowledgement failure, earlier compile and lint failures,
source-mutating formatter runs, the disk-exhausted Agentd build, and the unchanged
successful retry. Nothing in a later successful run rewrites an earlier failure.

Each execution records its actual command, base commit and changed-file hashes
before and after execution. A source-stable local component test is not an
exact-commit hosted source-head or merge-candidate qualification. A formatter or
fix command that exits zero while changing source remains recorded as unstable.
A failed build, zero-test filter, selected CI job or skipped downstream gate
does not establish that the required native tests ran.

`source-pair-manifest.json` binds the reviewed component files and the configured
Chain source/base/merge identities. Configuration and actual pair execution are
separate fields. `agentd-http-native-binary.json` identifies the real full Agentd
test executable used by the four HTTP controls; it does not represent a reduced
test-only replacement crate or a claim that every Agentd test was executed.

Read the original members without altering them:

```sh
tar -tzf evidence/system-security-20261030/local-executions.tar.gz
tar -xOzf evidence/system-security-20261030/local-executions.tar.gz \
  hepta-final-agentd-http-controls-retry.log
```

The receiver protocol still requires original operation identity, receiver-side
deduplication or queryable status, and reconciliation of Unknown outcomes. These
records do not establish exactly-once execution for an arbitrary external HTTP
service or a completed multi-repository production gate.
