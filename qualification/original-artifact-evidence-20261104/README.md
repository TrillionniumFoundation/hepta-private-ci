# Original artifact evidence verification

This isolated checkpoint restores read-only access to ten existing Actions artifacts after the transient execution environment became unavailable. It does not move product branches, rerun product tests, change production code, or grant production admission.

Each manifest entry pins the original repository, workflow run, workflow head, actual source commit, artifact ID, byte count and SHA-256. The verifier downloads only that artifact, rejects expired or mismatched metadata, validates every ZIP member CRC, and never imports or executes archived code.

Each source snapshot is compared with the immutable Git blobs from its exact original commit. The expected path set is independently obtained from the original reader's static snapshot declaration and Git index. Source links are handled according to that exact reader: the environment reader hashes link payloads; the other readers follow in-repository links and report both the original link object and the resolved blob digest. Before and after source snapshots must agree.

Recorded command logs and retained outputs are rehashed. Private-state native JUnit inventories must contain all four original libraries with no failure, skip, duplicate or filter selection; the original commands and Rust 1.96.0 are checked. Its Bazel evidence must retain the four exact labels and committed-first/update/check sequence. The Dylint checkpoint requires all 1,664 inputs, nine recorded outputs, three original zero-exit commands and identical committed/generated/Git MODULE locks.

Failed Windows environment and Memory artifacts remain failed. Their original logs are emitted with workflow-command interpretation disabled and their actual summaries, failed cases and panic blocks are retained. Successful evidence verification means these historical bytes and their source bindings were checked; it is not a new test pass or closure of whole CI. The original seven ignored Memory qualification probes remain part of their original result and are not converted to passes.

The workflow has contents/read and actions/read permissions. The ephemeral token is sent only to api.github.com, never to redirected artifact hosts, and is not printed. No artifact executable or product code is run. ZIP expansion and network reads are bounded. Each report and original ZIP is retained as a new artifact; source workflow and manifest remain on this durable checkpoint branch.

The Dylint lane also executes the independent reproducer from exact checkpoint b744660a0ebd2b31726c38445cab810a8c3b1626 against the same original ZIP and Git source. It requires its normal invocation to succeed and its Python -O invocation to fail specifically before producing a report. That independently reviewed script is checked out from Git, not loaded from the artifact.
