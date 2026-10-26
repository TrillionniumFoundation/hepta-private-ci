# SDK fixture process and home ownership

Every test creates a fresh private `CODEX_HOME`. The fixture registers that exact
path with `OwnedCodexHomes`; child processes carrying the path are attached to its
generation through the SDK imported `node:child_process` module. Other paths are
not adopted. No process is selected by PID, name, or system-wide search.

Closing synchronously changes the generation from open to closing before any
abort event or child `close` continuation can run. New spawns for that path are
rejected before invoking the operating system. The fixture aborts the generation,
waits for each owned child's `close` (including its stdio), and only then removes
the home. Closed generations remain fenced, so a retained old promise cannot
write into an already removed home or the next test's home. Closing is idempotent;
another open generation remains independent.

`fixtureLifecycle.test.ts` uses actual Node child processes. The first regression
starts a second child from the first child's `close` callback while teardown is
joining. The former snapshot implementation admitted the second child and returned
with it alive. The regression requires admission to fail and the home to be absent.
The second regression checks the retained old path, repeated close, and a second
live owned home via its real stdin/stdout. `execLifecycle.test.ts` separately proves
that production execution waits for its child and stdio during delayed exit.

These are test fixture changes. They preserve production `CODEX_HOME` ownership
checks, original SDK assertions, MCP baselines, and the original 5 s / 10 s test
limits. Passing the controlled regressions does not qualify the full consumer
suite, another CLI artifact, Asterinas execution, or production authorization.
The GNU Cargo `dev-small` CLI used in earlier SDK runs is distinct from the Bazel
executables built and warmed by `.github/workflows/sdk.yml`.
