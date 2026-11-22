# Native results on f5 and V8 checkout repair

These native results bind **f5eabeecd1e7a77493c933bb8cdabc8d7a81ea37**, tree **a8c8b4d0ec95180fe571348cd22fab5ba790c603**. The following source change, commit `278c76e8e34912e99f964b2099a49bf70a3dabc9` / tree `f8ab841517db29fbe02299a1bc5b2b8b73b13e3b`, only adds the repository's existing Windows long-path Git configuration before V8 checkout. It has not yet been natively qualified. This evidence append does not move main or retire branches.

## Confirmed native results

- **Windows private artifacts: 9/9 pass, zero retries.** Run `45044041266`, job `137274600302`, artifact `14763132226`. Exactly nine required terminal test IDs were observed, with no missing, duplicate, unexpected or failing IDs. The other 29 cases are outside this declared filter. Head, tree, Cargo lock, protected source and tool files are identical before and after execution. The final junction test-source SHA-256 is `b3e2c55d0663a2160466faa357db815f77ab8ba9418b5418fea7ec05560c5fbf`.
- **Original Bazel lock update/check: both exit zero.** Run `45044046139`, job `137274614926`, artifact `14762928565`. The accepted-candidate receipt binds exact f5. No tracked or untracked changes remain, and both lock files plus the module and Bazel-version inputs are unchanged. The generated lock patch is empty. This result does not claim native Rust execution.
- **Broader checks:** the archived main-bound snapshot records successful Windows shard 1, all three platform Clippy jobs and all three release build jobs. Blob policy, Codespell, canonical contract metadata, cargo-deny and Rust format also pass. Other required jobs remain failed or running; see their exact source-bound status in [VALIDATION.json](VALIDATION.json).

The nine-case Windows result is not the original 19-group / 175-case suite, AuthBus qualification, or production authority. No successful result is silently rebound to another commit.

## Unresolved command-location behavior

Run `45044047752`, job `137275431881`, retained both original and fresh runner-temp observations. All six original cases and all six relocated cases still miss their expected results. The AppContainer batch exits 22; both LPAC entry variants exit 1, including the minimal case whose original expected exit is 71. All 160 long/short-path queries under the observed child tokens return Win32 error 5.

The source and command image remain unchanged, cleanup completes, all six relocated fixtures lie under the fresh owned root, and native allowed-byte/deletion observations and outside/protected-file retention remain true. Moving location or changing path spelling did not fix command behavior. The observations run under parent impersonation and do not establish cmd's internal first failing operation or a single ACL cause. Original failures remain failures; no production claim or permissive fallback was introduced.

## V8 Windows checkout repair

Run `45044039649`, job `137274595679`, could not create two long registry snapshot filenames during checkout. The V8 test did not start, and the final cleanliness check also failed after that incomplete checkout. The retained raw log proves this failure stage.

The repair inserts one PowerShell step, `git config --global core.longpaths true`, before checkout, matching existing repository Windows jobs. Removing that one parsed YAML step yields the exact original document. All existing actions, exact source ref, credential setting, permissions, concurrency, commands, assertions, flags and final checks remain unchanged. Original formatting, pinned Prettier 3.5.3, spelling and whitespace checks pass; an independent review confirms the scope. Native verification must occur on a later published head.

## Remaining barriers and evidence

The operator's real-Git regression controls pass in new-head CI, but deterministic-merge materialization still fails and its later compile/test steps are skipped. Historical full-diff whitespace is not waived. Windows shard 3 and Linux musl are failed in the archived snapshot; the other in-progress jobs are not called successful. Main stays `732e934ba496d90fbe042b8d41d479ef901643e5`, no branch is deleted, and the HIA protection and exact automatic-review STOP described in [the preceding audit](../followup-b3/README.md) remain in force.

[EVIDENCE-MANIFEST.json](EVIDENCE-MANIFEST.json) records every member and stored/decoded archive part. Gunzip each numbered `evidence.tar.gz.part*.gz`, concatenate its decoded bytes in filename order, and open the result as a gzip tar archive. Every member was read back against the original size and SHA-256. All stored parts are smaller than the original 512,000-byte limit. The archive includes receipts, raw failure and success logs, downloaded artifacts, before/after observations, independent reviews and the publication/protection readback.
