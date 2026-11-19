# Correction: resolved program does not reveal the original request string

This note qualifies the immutable `MAC_FAILURE_REVIEW.md` blob `7d0f9a01fd68478557d644695b09de031816701b` and companion JSON blob `8b80754090fd794070e50a260cff7f8f019d0b1f`. The historical files and original failed job remain unchanged.

The earlier Markdown says that “the original CI log does not identify why the observed candidate was bare.” The table also calls it a “relative executable candidate.” My progress messages described the wrapper as receiving bare `touch`. These descriptions overstate what the original trace directly shows.

**The direct observation is only the resolved program `{physical cwd}/touch`, the original argv beginning `touch`, and the following Run/Escalate decision and `ENOENT`.** Original log lines 9465–9471 and 10556–10564 contain this sequence. The complete log contains no `EscalateRequest` dump or direct serialized `request.file` value. The server computes the displayed program with `AbsolutePathBuf::resolve_path_against_base(file, workdir)`. Bare `touch`, `./touch`, an absolute `{cwd}/touch`, and other equivalent path strings can produce the same displayed result. The original `request.file` spelling is therefore **UNKNOWN**.

The pinned zsh source analysis remains conditional: its direct `zexecve(arg0, …)` path-search branches require an empty/dot PATH component, while an explicitly hashed command can supply another spelling. That fact cannot identify which path the actual Mac binary took without its actual request string and executable identity. Changing Rust execution to search PATH again would alter the existing execve contract and is not justified by the current trace.

## Additional original evidence: the Bazel test action PATH

The original artifact `13838015751`, `bazel-execution-logs-test-aarch64-apple-darwin`, has now been downloaded in full and verified against GitHub's digest. ZIP size: 10,855,234 bytes. SHA-256: `7731d0837a1597aadc19ea6d69f167f372c9bebe37e79631fb0f7b96ad9e9af0`. It belongs to run `42971470498`, exact source head `2ae5215beaf8d7b7df111a090b82134beae2683d`.

Its compact log was decoded using the pinned Bazel 9.3.0 protobuf fields and checked against invocation `d2fec41d-b448-48ad-b477-637d62508154`. All 29 original `core-all-test` main TestRunner actions have the PATH:

```
/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
```

Those 29 main actions are local, uncached, and contain the original 19 exit-101 failures and 10 successful action exits. The same target also has 29 auxiliary `generate-xml.sh` spawns; they are separately identified and do not represent another 29 tests. Historical decoder versions V1/V2 counted all 58 selected TestRunner spawn records under a field named `selected_test_actions`; the final V3 uses explicit main/auxiliary counts and preserves the older derived files.

This is actual **Bazel test action** environment evidence. It agrees with `.bazelrc`'s `--test_env` setting, rather than a compile action's `--action_env`. It does not observe the later zsh child's environment after runtime setup or shell startup. The Linux inert control, if separately executed, has its own identity and cannot be combined with this Mac log as though it were a single dynamic trace.

The original ZIP is retained once in `original-execution-log/`. `CORE_TEST_PATH_OBSERVATION_V3.json` records only the selected target, PATH, action/entry identities, outcomes, and safe executable-basename markers; no other environment values are projected. `extract_core_test_path.py` is an offline decoder and never executes an archived command. This evidence adds no native test, model request, or repaired-source qualification.
