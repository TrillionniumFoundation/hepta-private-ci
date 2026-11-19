# Actual isolated validation of 4537458b51b6

Fixed source: `4537458b51b6ca936264aecea7cfe384b941d0d1` / tree `8cbd7b269c9c39df4ee3ffcefed8473060696184`.

The original H job `1a1d0856c55-2564-1b94` is **failed / exit 1**, complete and durable, without timeout or cancellation. The immutable original SDK terminal payload is retained verbatim. This is not a successful combined native validation.

## Source result

The complete original 89,701-byte source report has SHA-256 `3e43193067b7f73768968f00835ae8908fea916fed19645c9032051a7baa9f89`. All **443 methods in 62 modules passed**; failures, errors and skipped methods are all zero. Root checked all 443 unique IDs, their exact multiset and sequence against the original a671 report. The source runner remains the original 0397e37ba2f93117bede8ab547404a72b8f9946c, SHA-256 4e0d8e41eff59aee3d18f1a85080a15c2c4e3bd8a002e25751bdfa40dadffdf4. The report records 297.22826777002774 seconds; the outer source process records 298.4196590699721 seconds and exit 0.

## Native preflight failure

The complete 677-byte original stderr records `FileNotFoundError` at native-runner.py line 36, `target_root.lstat()`, for `/data/hepta-learn-ce434-runtime-20261112-v2/target`. The exact driver blob is 21cb4ab3dc65c459d1bdb87b07c39c3c6c0c067c. This path occurs after creation of the isolated native evidence directory and before the helper build, short TMPDIR creation, native test command and first native result report. The driver exited 1 after 0.2964633130468428 seconds. No native cases ran in this attempt, and there is no native result-file hash in the outer record.

The observation does not establish why the target disappeared. Later native file_info requests rejected directory paths as invalid regular files/private sidecars; those rejections do not establish directory existence. The old 2,506-byte e5c/v2 creation receipt was reread intact with its original hash and remains historical provenance. Recovery must establish a new target's real identity and original input hashes before testing; old identities and receipts cannot be relabelled.

## Source and scope

The outer original record confirms the previous a671 worktree remained clean and unchanged, and the new isolated worktree was clean at 453 before and after the attempted validation. No old checkout command or cleanup was issued. The standalone caller scanner step is only its self-test and does not count as the full caller proof.

This directory contains the complete listed reports and stderr, plus their readback metadata; it does not claim to contain every original log. Evidence-only commits do not change the tested source. Source pass does not erase the failed outer or establish native, Root29, formatting, positive adoption, complete ordinary NoUpdate/fallback, fresh different-input C or daemon/Root cold-restart acceptance. All four ordinary acceptance counters remain zero.
