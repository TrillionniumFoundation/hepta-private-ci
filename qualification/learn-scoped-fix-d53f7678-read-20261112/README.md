# d53f7678 scoped fix: read-only result observation

This directory preserves the exact result file read from the already completed H job. This evidence operation did not launch Rust, tests, or another process on H.

- Source: `d53f7678860d6f2ab6b3a6143ea1ceb37bdb2c9f`.
- Tree: `abc89d1ce05ba27f3a56a7601ccfd22de3051b47`.
- Observed status: `completed`, exit code `0`, `source_unchanged: true`.
- Original start: 2026-11-12T23:04:27.995011+00:00; finish: 2026-11-12T23:06:20.876011+00:00; elapsed: 112.8809201340191 seconds.
- Both source snapshots were clean and contained 15,494 tracked files with aggregate SHA-256 `d5949de0790d5c19e36fc322687e91e7086737fe73e8465a304258f32bd3765e`.
- The exact result is 4,018 bytes with SHA-256 `7913a3bc803b0c79ff4b50b0db69bbe6a999d11d34e3b81854844a7a5065d82c`. Its local bytes match the H read tool's full-file size and digest.

`h-read-response-0.original.json` preserves the original tool text, including the pinned file version. `verification.json` records the local checks and observation time. The result names log hashes; those log bytes were not fetched in this narrow observation. This directory is not a complete archive of the run.

The command was scoped `just fix`. This observation establishes its reported completion and unchanged source. It does not establish any executed test result, A success, or end-to-end Adopt / evaluated NoUpdate / cold-recovery success.
