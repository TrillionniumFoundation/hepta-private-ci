# Owned CLI process lifecycle

`CodexExec.run()` owns the CLI child and its stdin/stdout/stderr handles. The
async generator completes only after the child's `close` event, which follows
process termination and closing its stdio. Returning early from iteration or
throwing during setup closes readline, requests child termination and joins
that same close event. Error listeners remain installed until that boundary;
cleanup removes only the listener created by this run.

Tests create private `CODEX_HOME` directories. Their fixture records only child
handles spawned with that exact home. Teardown requests termination of any
remaining owned child and joins all recorded close events before deleting the
home. A test timeout does not cancel its original promise, so this teardown is
required even when the normal generator cleanup has not run. A child that does
not close keeps teardown pending; an active runtime home is not safe to delete.

Run the original consumer suite from the repository root:

```sh
pnpm -r --filter ./sdk/typescript run test
```

`tests/execLifecycle.test.ts` launches a real Node child whose termination is
delayed. It verifies that an early consumer return joins child close; the same
test fails with the original implementation. The existing fake-child fixtures
emit real process ordering (`exit`, stdio completion, `close`) and retain their
original assertions. The existing abort and consumer cases keep their original
5/10-second limits. The earlier intermittent timeouts and cleanup race are
separate observations; a successful run does not identify every timeout cause.
