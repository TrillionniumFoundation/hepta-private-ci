# Notes buffered replies after a macOS peer closes

A Notes peer may write a complete response and close its socket before Agentd reads the response body. On macOS, setting the read timeout on that closed connection can return `InvalidInput` (`EINVAL`) even though the complete response remains buffered. The original transport returned immediately and reported an ambiguous exchange.

## Change

The read loop retains its existing two-second total deadline. Only on macOS, when setting the read timeout returns `InvalidInput`, it enables nonblocking mode, reads immediately available bytes, and restores blocking mode before interpreting the read result. A failed restoration remains an error. An incomplete response, EOF, or `WouldBlock` cannot produce an accepted frame. The change adds no wait, effect retry, or deadline extension.

Two real `UnixStream::pair` regressions close the peer before the first read: one leaves a complete frame buffered, and one leaves a truncated body. The existing seven Notes channel tests run alongside them.

## Native validation

| Run | Actual result | Notes |
| --- | --- | --- |
| macOS, original implementation plus new regressions | 6 passed, 3 failed | The existing exact-frame exchange and both new regressions failed. The local profile retried each failure once; all three failed again. |
| macOS, fixed implementation | 9 passed | Every selected test passed on its first attempt. |
| Linux, fixed implementation | 9 passed | Every selected test passed on its first attempt. |

The official command on both hosts was:

```sh
just test -p codex-hepta-agentd --lib --locked -E 'test(notes_channel::tests::)' --status-level all
```

The macOS run filtered out 310 unrelated tests; Linux filtered out 742. These results cover the selected transport tests, not the complete crate or workspace suite. The complete original macOS run returned exit code 100. The archival wrapper itself returned success after preserving that failure; `RESULT.json.exit_code` records the actual test result.

A separate native Rust diagnostic extracted the exact `remaining` and `read_before` functions with the same two new tests. Both diagnostic tests failed before the fix and passed afterward. Its source and logs are retained as helper evidence and are distinct from the official nine-test runs. The earlier Python socket probe is also labelled separately.

The initial macOS staging attempt failed because the new worktree inherited an empty sparse checkout. Its original traceback and process receipt are preserved. Only that worktree's sparse checkout was disabled. Rust 1.95 was discovered as the host default; the official runs used the repository's pinned Rust 1.96 toolchain.

## Source and evidence identity

The functional commit is `a4f85fef87942a414a26051e8dd403f6aeea8319`, based on `f49128e503b24bb52ccdb32a860939e6392c8e08`. It changes two Rust files by 53 insertions and two deletions. The production file and test file used by both successful runs have identical hashes.

The final official `just fmt` completed after all tests and changed no bytes. The committed Rust sources are therefore byte-identical to the tested sources. No tests were rerun after formatting.

`MANIFEST.json` binds the source files, command identities, exact selected results, and `evidence.zip`. The ZIP retains complete original build/test stdout and stderr, command and source-hash receipts, the sparse-checkout failure, helper sources, original and fixed source snapshots, formatter receipts, and a manifest for every archived file.

- Archive SHA-256: `21c511ebe9bd1f825b80be3bc687f353aa0a94e8972c8b49dd21dc719a6c590e`
- Archive size: 101188 bytes
- Total exchange deadline: two seconds

The tests use native in-memory socket pairs. They do not access real Notes application data or prove application delivery, research benefit, or activation of any research gate.
