# Two additional historical replay workflows

These originals were copied byte for byte from commit
`639f84c1aafa6fb5044b690ae21706a7782861ef`. The adjacent
`additional2-replay-custody-manifest.json` records each source Git blob,
mode, SHA-256, first117 source identity, original input head, triggers, and budget.
Any formatting difference from the earlier first117 snapshot is recorded as a
different blob; it is not hidden by a semantic-equivalence claim.

## Reason for the move

The lifecycle-policy and scoped-archive workflows accepted pull-request events
that changed their declared workflow or helper/test paths. Introducing those
files in this convergence PR could therefore automatically build or execute
fixed historical sources, fixtures, or archived native tests. Those runs would
not establish the correctness of the current candidate and are outside this
task's boundary against executing historical programs.

The two active workflow paths are removed. Their exact original bytes remain in
`originals/.github/workflows/`, outside GitHub's active workflow directory.
The original scientific and product qualification limits remain unchanged.
No historical program or workflow is executed by this change.

This is an independent supplement to the original 113-file archive and the
separate four-workflow host-operation supplement. Their manifests and original
contents remain unchanged. No current required CI check, test budget, formatter
exclusion, spelling exclusion, or test exclusion is modified. Two exact
`-text` attributes only preserve these archived byte streams on checkout.
