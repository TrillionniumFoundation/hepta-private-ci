# Original host test execution

The original macOS ARM Clippy job 126074520987 selected
Linux RBE compiler tools but executed the tagged Rust test's compiler action
inside the Darwin sandbox. The Linux `process_wrapper` failed with exit 126.
The `no-remote-exec` tag was intended for the real `/usr/bin/ssh-keygen` tests,
but also applied to their Rustc and Clippy actions.

Use the existing `workspace_root_test` launcher for the original public test
target and put the unchanged Rust test binary behind it. Keep both freshness
and local-execution tags on the launcher, retain every original test, and let
the compiler actions use the selected execution platform. The launcher keeps
the original working directory and forwards test arguments.

The hosted qualification uses the existing authenticated RBE configuration on
macOS ARM and Linux x64, runs the original Clippy aspect and every Rust test,
then inspects the actual action graph. The original Clippy selector must still
include the complete Rust test binary, which is explicitly linted; an aspect
on the launcher alone does not establish test-crate lint coverage. Both its
Rustc and Clippy actions must exist. It fails if compiler actions inherit
the runtime restriction or the public TestRunner loses it. It requires zero
ignored or filtered tests and snapshots the exact inputs before and after.

Native hosted qualification remains pending at initial publication. This
change does not close other repository, scientific, or release blockers.
