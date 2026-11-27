# Native Windows consumer readback at fb00

## Exact source and evidence

- Source: `fb00e4422c293ffb318c9d7535e1991a3bbac707`.
- Run `45434906085`, job `138589954514`: completed with failure.
- Final artifact `14942967612`,
  `hepta-windows-durable-fb00e4422c293ffb318c9d7535e1991a3bbac707`.
- ZIP SHA-256 checked against GitHub:
  `54d99a5d1a0c365f268032cd18837c69dbd729bcb492b41e07939ca59e2e0761`.
- Artifact `head.txt` identifies the source above and `rustc.txt` reports
  Rust 1.96.0 on `x86_64-pc-windows-msvc`.
- The complete decoded job log was also retrieved, separately from the
  structured step summaries. Its local text copy normalizes CRLF to LF;
  the artifact files preserve their original bytes.

| Selection | Actual result | First observed blocker |
| --- | --- | --- |
| Native private primitives | 12 run, 10 pass, 2 fail, 5 outside selector | SQLite ordinary-created file privacy check; directory metadata missed a new child |
| Native registry owner | 2 run, 2 pass, 26 outside selector | None in this selection |
| State recovery | 6 run, 1 pass, 5 fail, 203 outside selector | Three retained-identity errors and two private-object errors |
| Cognitive recovery and normal store | 23 run, 0 pass, 23 fail, 249 outside selector | Every case stopped at `Invalid("cognitive root is redirected")` |
| Directory/schema/lease consumers | 0 executed; compile failed | `MultiAgentMode` not in scope in app-server library |
| Prompt/final-use consumers | 0 executed; compile failed | The same app-server library error |
| Scoped Clippy and post-fix diff check | Completed successfully | Warnings remain; this is not a zero-warning claim |

The state and cognitive failures are not silently attributed to one owner
problem. The cognitive rejection is a distinct earlier check. The independent
`db23` probe subsequently resolved the namespace failure and identified a real
owner inequality, as recorded in the sibling SQLite-native qualification.

## App-server compile correction

`thread_settings_from_config_snapshot` is production code and uses
`MultiAgentMode::ExplicitRequestOnly`. Its required import was accidentally
behind two `#[cfg(test)]` attributes, so ordinary library compilation failed at
`app-server/src/request_processors/thread_summary.rs:190` with E0433.

The change removes those two guards from the import. The production value,
permission behavior, protocol shape and public APIs are unchanged. This is a
source compilation fix, not a change to delegation policy.

Repository `just fmt` and `git diff --check` passed. No new local app-server
build was started: the next normal integrated Windows run must prove this
large consumer graph compiles and executes the retained selectors.

## Artifact file hashes

- `tests.log`:
  `2933a21afab5cb0d91eb0487da78eb868da2cee73237917b0f53a8527401aca5`.
- `prompt-consumers.log`:
  `ce1b5de8aa8ef6bdeb03f29169d6166eb5806ef86dafdf061e46290cfb69fea9`.
- `sqlite-recovery.log`:
  `930c93aa52340fa2a964acb598c50f2e7aef5ec9557350aec5a114a24128ce2f`.
- `cognitive-recovery.log`:
  `49d021ab3660495bf5ad19a28ebae45186971aa89989a2593ea78cf191eb8fba`.
- `native-clippy.log`:
  `eb71a4e8be001e4d2ea35a9303218242fad0ca252b7dd5a6340fd7da42c15c7b`.
