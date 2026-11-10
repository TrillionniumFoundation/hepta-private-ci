# Fixed-source dependency proposal, not an adopted upgrade

The published CTRL source at `99b194e64c83eb997344680b715c318d8e0d3cc8`
still locks rmcp 3.1.3 and libsqlite3-sys 0.37.0. Primary RustSec advisories
require rmcp at least 3.9.0 for all three current findings and libsqlite3-sys
at least 0.39.0 for the bundled SQLite finding. No advisory is ignored.

SQLx 0.9.0's released SQLite driver excludes libsqlite3-sys 0.39. The
upstream bound-only fix is commit `10462fa4414c6c7f1ed1d39bb31678e3b726878c`.
The disposable runner verifies the original official crate archive checksum,
vendors its exact source, expands only both manifest bounds, and proposes
libsqlite3-sys 0.39.1, rusqlite 0.41.1 and rmcp 3.9.0. The CTRL branch's
Matrix 0.19.1 manifest patch is preserved separately from main's Matrix 0.18.

The workflow resolves Cargo, regenerates and checks the Bazel lock, executes
scoped RMCP/state/Matrix consumers, and runs the existing no-suppression guard
and cargo-deny action. All preparation, resolver or test failures remain failures;
the artifact retains the proposed diff, both lockfiles and each stage's result.
There is no commit, push, merge, deployment or automatic adoption in the runner.
Manual lockfile editing is prohibited; failed resolution does not qualify a patch.

Even a passing proposal would not validate custom HTTP boundaries. Existing
OAuth clients use a custom client outside the upstream resolved-address policy;
the local HTTP adapter needs independent buffered-response limit tests for
legacy and initialization paths. Full consumer/platform qualification remains
necessary. No third-party vulnerability is reproduced by this workflow.

Preparation validation: five synthetic tests passed, including a disposable Git
checkout and exact-byte archive extraction. Standard `just fmt` passed for the
new Python files in an isolated checkout with the original formatter and locked
project; source bytes were unchanged. Prettier, YAML, action pins and Bash syntax
also passed. No Cargo resolution, patched build or security qualification is
claimed by those preparation tests; the actual workflow must establish them.

The first workflow validation attempt (`42776575326`, zero jobs) is retained as
a failure. Its runner-only temporary path was incorrectly placed in global
workflow env. The follow-up binds it inside an actual runner step; no dependency
calculation or test ran during that first rejected attempt.
