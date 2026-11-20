# Mac crossterm exact shallow dependency preparation

One isolated dependency fetch completed successfully. This is dependency material preparation, not a new native experiment or evidence that the project tests pass.

| Item | Actual result |
|---|---|
| Public repository | `https://github.com/openai-oss-forks/crossterm` |
| Locked commit | `45fecb9508105988f42fe6ff0441783ed3717f92` |
| Root tree | `f43069917d73c60e5286f56fef318cb13febf204` |
| Fetch attempts | 1; no automatic retry |
| Fetch command | `/usr/bin/git -c http.version=HTTP/1.1 fetch --depth=1 --no-tags https://github.com/openai-oss-forks/crossterm 45fecb9508105988f42fe6ff0441783ed3717f92` |
| Fetch | exit 0, 22.761068167 seconds |
| Whole owner | exit 0, 22.896532957999998 seconds |
| Owner limit | 120 seconds; physical watchdog 119 seconds |
| Owner | `dpty-060e8903cfbf2dc630728a6bb27fdd69e2547d907587fd1bee7786433514386b` |
| Remote object store | `/Users/qianqi/work/hepta-joint-mac-fixtures-20261120-e9e051/dependency-crossterm-shallow-1/objects.git` |
| Retained object files | 166330 bytes: pack 161686, index 4152, reverse index 492 |
| Reachable shallow objects | 110: 1 commit, 24 trees, 85 blobs |
| `git fsck --full --strict --no-reflogs` | exit 0 |
| Exact RESULT SHA256 | `e2d5013e0ff4523588901edee73d34189838d59b40090a9b8079b7a46bd79328` |
| Exact pack SHA256 | `9917bd1f5017d1e5cb2fe56b9411d7b10c079a1f632ae7bd82349b5bc4cd6485` |

The commit and root-tree raw Git object hashes were recomputed on Mac and independently recomputed after readback. All 36 requested remote original files were retrieved and checked against their remote SHA256 values. Binary pack chunks used the same immutable version token. The pack trailer SHA1 is `ce382f52d1c25cdff46fd6f7acbe08929ce6c3c4`, and its encoded object count equals the retained 110-object inventory. The bare HEAD, config and refs are unchanged from their post-init state. The wire transfer byte total was not measured; 166330 is retained object-file size, not a network traffic estimate.

This preparation did not modify the original Cargo cache, source, lockfile, refs, global Git config or running native4 owner. It started no Cargo process, model, training update or native experiment. Its only subprocess signals would have targeted its own newly created Git process group on timeout; no timeout or signal was needed. A subsequent, separately authorized cache seed or project test is a distinct operation and is not included in these counts.

The original successful source, launch arguments, PTY receipts, raw remote read responses, exact command intents/exits, original stdout/stderr, commit/tree bytes and complete small object pack are retained in the archive. Prior native dependency failures remain separate and are not superseded by this preparation.
