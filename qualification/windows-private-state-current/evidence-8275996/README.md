# Original private-state qualification, including failures

This evidence-only checkpoint preserves exact source 8275996f2c589a96843e116ac6f2c1d194ef3d2b and all four original ZIPs from workflow 41713496978. It does not change the product branch or transfer results to a later commit.

| Original job | Actual outcome |
| --- | --- |
| Linux native | All four complete libraries passed: path utilities 7, contracts 174, prompt registry 50, Agentd 173. Total 404, zero skips; scoped Clippy passed. |
| macOS native | Path utilities 4, contracts 174 and prompt registry 50 passed. Agentd ran 173: 166 passed, 7 failed, zero skips. Scoped Clippy was not reached. |
| Windows native | Two selected acquisition positive cases ran and passed; 15 unrelated cases were filtered. The reader rejected nextest progress columns. Neither mutant nor any complete library ran. |
| Bazel | Original committed-first check, update and repeated check passed. All four original complete library targets actually executed and passed with test caching disabled. |

The seven macOS failures are retained verbatim in original JUnit: three HNMF roots and one external replay checkpoint fail canonical-path validation; three sockets exceed the native path length limit. Windows actual filesystem observations confirm the positive acquisition cases; the wrapper still failed and is not labeled passed. The narrow successor keeps the original assertions and gates and requires a new complete run.

## Source and original byte verification

The independent verifier streamed 99,684,160 original Git blob bytes. Of 8,874 distinct recorded input paths, 8,873 match their exact Git blob bytes. The one remaining path, codex-rs/vendor/bubblewrap/LICENSE, is Git mode 120000 with the seven-byte link text COPYING. All four hosted snapshots hash the resolved 25,383-byte COPYING content. Both link and target Git identities and SHA256 values are recorded explicitly. This is a resolved-link representation, not a claim that its bytes equal the symlink blob.

All four before/after maps match that verified checkout representation. Every command-log hash, uploaded native JUnit result, archive size/digest and ZIP CRC was checked. The generated MODULE.bazel.lock equals the committed 1,701,389-byte file, SHA256 1a58f7d1fcbfe850d18a01c19faf15c941dfd229cb8caeb406dbe8ce8c99522e. The Linux pinned D-Bus prerequisite reports 52 successful commands and exact recorded inputs. Bazel retains full command logs; no separate Bazel XML upload is asserted.

## Restore and verify

```bash
python3 PATH/restore.py --output /tmp/private-state-original-results
python3 PATH/verify_827.py --repo . --artifacts /tmp/private-state-original-results
```

Use a clone containing the tested commit and replace PATH with this directory. Raw binary parts are at most 384000 bytes; concatenation reproduces each original GitHub ZIP exactly. The verifier reads Git blobs, logs, metadata and XML. It does not run any archived code, native binary, Cargo or Bazel.

The original Windows/macOS failures and broader required CI remain open at this source. DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO remains in effect.
