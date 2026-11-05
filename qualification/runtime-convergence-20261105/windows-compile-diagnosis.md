# Windows Agentd qualification compile blocker

## Conclusion

The original exact-a20 Windows job fails while compiling its Agentd test binary, before any selected Prompt Runtime test executes. This is a production Windows PTY error-conversion defect, already present in the R3 source base. It is not an observed Prompt Runtime assertion failure, an A-line arithmetic regression, or a SQLite test-fixture failure.

The existing source-only repair in PR #4854, commit `345dd470a64783b54f45c522ac8675435d204738`, is accepted for this narrow defect. The accompanying `windows-pty-clone-error.patch` reproduces that donor exactly. No new competing source implementation, test, feature, signature, timeout or workflow change is included.

## Original evidence

- Failed run: `41982971524`; job: `127097094121`.
- Exact source: `a20a8191ec37375876a99b7c18bae053f9bc185d`.
- Full original log: `windows-job-127097094121.log`, 153,709 UTF-8 bytes; SHA256 `d067c57935f90cee93924d5658ca809e5a426c4b6036f48c7f75654390c072c9`.
- Log line 636 records the unchanged command: `just test --locked -p codex-hepta-agentd --lib -E 'test(prompt_runtime::tests::)' --test-threads 1 --no-tests fail --retries 0`.
- Lines 1320 and 2030 record the actual `filedescriptor v0.8.3` dependency download/compile.
- Lines 2045–2066 report `E0277` at `utils\\pty\\src\\win\\mod.rs:79`: `OwnedHandle::try_clone()` returns `Result<_, filedescriptor::Error>` and `std::io::Error` has no matching `From` conversion. `codex-utils-pty` fails to compile.
- Line 2068 records Agentd `cargo test --no-run --package codex-hepta-agentd --lib --locked` exit 101. The recipe and step subsequently fail.

Four earlier nextest groups completed with 15/15, 2/2, 3/3 and 2/2 tests passing. Those results do not establish Agentd Prompt Runtime qualification. The original formatting and native acquisition-attack steps after this failed step did not execute. No original attack result or P0 closure follows from this run.

## Exact source and existing repair

`codex-rs/utils/pty/src/win/mod.rs` at both R3 base `4e31abc907f09740d402d1ddef7a1d2fe0a366a6` and a20 has blob `41eef9a7053ff2ac2f4aa23abd4fe9d5f25676bf`. `WinChild::observe_exit` returns `IoResult<Option<ExitStatus>>` but applies `?` directly to `try_clone()`.

The donor's sole parent is a20. Its only changed file is that Windows PTY module, final blob `d244e22befecda19782f1fc2a696af1a534069b0`. It explicitly maps the clone error to `IoError::other` with the original error's display text and operation context. Clone failure remains an error before any wait or exit observation. The native signal, WAIT_TIMEOUT, WAIT_FAILED, exit-code-259, query-error and descendant-preservation branches are unchanged.

The original Windows observation tests remain blob `45d6ece35f88b73d87a95ec148e130341e059ec9`, including insufficient SYNCHRONIZE access, query failure after a native signal, and genuine exit code 259. No test assertion is weakened.

PR #4843 head `6730f2a634e3d928241145cc15f68f6f296ef9c8` instead has the older PTY blob `05063cf66a69f9b0855e54a537ce7d53947e5424`, using the old STILL_ACTIVE implementation. Its SQLite fixture work does not repair this compile route. Replacing this module with that older source would also discard the R3 native-observation semantics.

PR #4854's later commit `0856b142808f102c75e1182cd4dfb5e798938d84` adds a separate workflow. It is excluded from this source-only patch. Its supplemental run `41988311741` was queued with no conclusion at the direct readback; it is not native success evidence and cannot substitute for the original workflow.

## Checks and required execution

The original log SHA, exact source blobs, donor parent, sole-file diff, clean patch application, final donor-byte equality and whitespace check were verified. No native compilation or test was run by this reviewer. Further compiler or test failures may appear after this first compile blocker is removed.

Keep and rerun the complete original Windows qualification workflow on the corrected exact head. In addition, the existing native PTY observation tests provide focused coverage without changing test code or budgets:

```text
just test --locked -p codex-utils-pty --lib -E 'test(win::observation_tests::)' --test-threads 1 --no-tests fail --retries 0
```

Both commands must run on Windows with the pinned toolchain. A Linux build cannot qualify this Windows-only code. The subsequent original directory-acquisition attacks must still execute and pass before their own blocker can close; #4844 containment is not treated as a repair or proof for those attacks.
