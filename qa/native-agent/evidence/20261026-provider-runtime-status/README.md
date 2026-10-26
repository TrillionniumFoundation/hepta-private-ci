# Native provider and runtime validation status

The scoped native-provider test gate passed **352/352**. The recorded runtime full gate still failed **3 tests** (1,151 passed, 21 ignored), and the one ordinary live provider marker returned **HTTP 400 / `model_not_found`**. These receipts support further integration work; they do not admit a production native agent, a live token-cap witness, a two-round tool continuation, or a same-model Codex comparison.

This is an evidence-only report for [source PR #3976](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3976). The 95-file original snapshot binds source `63b22b4fd29440c00680ed3111aadc6c84d18627`. The later stack target is `e21e1054a0f9e7a63e4e77b8e06fac71d42f6375`, which adds the narrow `.codespellrc` exclusion for existing raw evidence. This report makes no claim that CI passed on that newer head. Source preparation, individual test runs, and built binaries retain their own identities below.

## Recorded status

Evidence IDs resolve to exact archive member paths and SHA-256 values in [evidence-map.json](evidence-map.json). Original files remain compressed and unedited.

| Check | Recorded outcome | What this establishes | Evidence |
| --- | --- | --- | --- |
| Combined native gate v2 | 349/350 passed; exit 100 | Original incomplete-stream test failure is retained, including its failed retry. | N2 |
| Combined native gate v3 | 351/352 passed; exit 100 | Original cursor-race timeout is retained, including both 60-second attempts. | N3 |
| Combined native gate v4 | 352/352 passed; exit 0; all 8 admission races present once | The specified three-package, two-feature test gate passed on its recorded candidate. | N4 |
| Native source finalization | Scoped fix, format, lock update, and build succeeded | Build/tooling evidence; lock update is not a Bazel test run. | BUILD |
| Final build continuation | Earlier wrapper timed out at 1,800 seconds; a later same-source build exited 0 | The interrupted build and subsequent successful build are both preserved. | RESUME |
| Runtime full serial gate | 1,151 passed, 3 failed, 21 ignored; exit 101 | The complete recorded runtime gate remains failed. | RT_FULL |
| Runtime other gates | Clippy, binary tests, and doc tests exited 0; initial format check failed and a later format check passed | These checks do not erase the full-suite failure. | RT_OTHER |
| Pending-index diagnostic | Instrumented original case failed; separate tmpfs exact case passed (1 case, 1,174 filtered) | Functional tail assertions ran under tmpfs; the original ext4 performance gate remains open. | RT_SYNC, RT_TMPFS |
| Crash canaries | Two actual controller SIGKILLs; one resumed original job and one cancelled original job | Recovery for two bounded jobs on the recorded old driver, using original-key lookup without a replacement start. | CRASH |
| Ordinary live marker | One request; HTTP 400, `model_not_found`; zero visible output; unqualified | A real request failed and its owner terminal was recorded. It is not a successful generation or model-availability proof. | MARKER |
| Offline owner inspection | Ten catalog entries; configured slug used fallback metadata | Configuration/model metadata alone did not establish provider support. | INSPECT |
| Installed Codex catalog | Codex 0.144.1 returned five catalog entries; no `gpt-6.1-sol`; zero Responses generation | Metadata observed through the installed original owner, with cache/version/originator confounding. | CATALOG |
| Standalone composition v1/v2 | Both failed before Rust test execution | The recipe error and dependency-resolution conflict remain recorded failures. | STANDALONE |

## Native test and build scope

The combined command selected `codex-api`, `codex-hepta-agent-loop`, and `codex-hepta-agent-qualification`, with `managed-responses` and `automation-effects`, and one test thread. The v4 JUnit contains 352 unique test cases, zero failures/errors/skips, and no retry or flaky annotations. All eight required fresh-owner admission races appear exactly once. Its JUnit test time is 63.067 seconds; its wrapper wall time is 65.230952 seconds. Neither is an end-to-end agent latency benchmark. [N4]

V2 failed `response_incomplete::tests::incomplete_is_reported_without_waiting_for_server_eof_and_cannot_be_completed`. V3 failed `concurrency_tests::tool_completion_and_cancellation_have_one_cursor_winner`, with attempts of 60.129 and 60.247 seconds. V4 retained the original timeout policy, retries, feature selection, case count, and temporary-directory setting; its receipt states source unchanged during that rerun. The reason receipt does not claim that all other host activity was known. [N2, N3, N4]

V4 precedes the final fix/format and source-publication stages. Its passing JUnit is not relabeled as a fresh execution on every final published source byte. The source inventories, subsequent build receipts, and publication verification preserve that distinction. The 15 newly staged source commits plus two existing prefix commits produced the original 17-commit source PR; the later codespell-only commit is outside this 95-file snapshot. [N4, BUILD, SOURCE]

The final build wrapper timed out after 1,800 seconds, after its fix and format stages had succeeded. An authoritative terminated-process result preceded a new build invocation. That continuation exited 0 in 167.844453 seconds, kept all 54 inventoried source hashes unchanged, and retained the timeout receipt. It did not rerun the tests or silently replace the failure. [RESUME]

The recorded final binaries are:

| Binary | Bytes | SHA-256 |
| --- | ---: | --- |
| `hepta-native-provider-qualification` | 765,420,664 | `e8fd23d273a040fd89d38b03e2f8e5c4f429fa56adff92a0a77df5987adfe6ba` |
| `hepta-native-provider-cap-witness` | 764,841,016 | `b00651787b8ee995b6ba3cd0228b57ce7a6370317212bb4958d5861b01eb7de5` |

The binaries themselves are not distributed in these evidence archives. Their identities are the executing host's preserved binary manifest. [RESUME]

## Runtime: functional evidence and an open persistent-storage gate

The full `cargo test --all-features -- --test-threads=1` result failed the scratch-heredoc/piped-read case, the continuously published pending-index case, and the archive-history/no-cross-owner-leakage case. The original log and exit 101 are retained. Clippy, binary tests, doc tests, and the later successful formatting check have their own scope. [RT_FULL, RT_OTHER]

In the instrumented pending-index run, the fixed writer issued 512 successful `fsync` calls for 64 requests. After its first four sync calls, the remaining 508 consumed 51.402222 seconds within a 55.767674-second writer span. This identifies dominant synchronous durability waiting in that instrumented run. It does not identify pure device latency, quantify tracer overhead, prove the same timings in earlier untraced runs, or justify removing the original durability/acknowledgement barriers. [RT_SYNC]

The supplemental tmpfs run used the same recorded test binary (`a9095dc508ffeaf26d3291674714986bb87bd2bfaa6eaba2de89dae825624957`) and unchanged original query/writer limits of 3/10 seconds. It passed the one exact case, reaching the final statistics, pending-entry, cached-byte, and post-flush assertions. Volatile tmpfs has different persistence semantics. This result does not establish ext4 performance, power-loss durability, or an all-green runtime gate. [RT_TMPFS]

The two crash canaries used old driver SHA-256 `3b2e84da41849da9558623b99669b8c4b0392fbaaea15bd3fcf3af309870933c`. Each controller actually exited with SIGKILL (-9); each job had one worker entry, four successful original-key lookups, changed-payload refusal, and null lookup for an unknown key. There were zero post-fault replacement starts. One original job succeeded; the other original job was cancelled with exit -15. The earlier configuration-rejected canary is also retained. These were same-account localhost SSH/operator tests under OS permissions, without a filesystem/network sandbox, host reboot, or production authorization. New process-port driver code requires its own qualification and cannot inherit these two results. [CRASH]

## Provider route and catalog observations

The ordinary marker used the configured `gpt-6.1-sol`, reasoning effort `max`, original ChatGPT auth owner, and `configured_jwt_only` policy. The reservation arguments were 8,192 input tokens and 1,024 output tokens, with separate 60-second bootstrap and generation limits. Its ordinary request schema did not expose a provider hard output cap. It performed one provider call without automatic retry, returned HTTP 400 / `model_not_found`, and recorded the terminal failure. Usage and server model remained null, visible bytes were zero, and no tool calls executed. Root did not admit a cap-witness, two-round continuation, or same-model Codex A/B run after this failed marker. [INSPECT, MARKER]

The offline inspector's ten-entry catalog and fallback metadata for the configured slug did not prove availability. The installed Codex 0.144.1 metadata-only AppServer invocation returned five entries, with `gpt-5.6-sol` marked default and no `gpt-6.1-sol`. The catalog's default flag is not a claim about the user's configured model. The captured initialization used public integration name `hepta_model_catalog_audit`; no thread/turn/Responses generation was requested. [INSPECT, CATALOG]

Both cache samples were taken after process start. The first recorded cache had client version 0.164.0 and nine slugs; the later cache had client version 0.144.1 and the same five slugs returned by `model/list`. Other owner writers were not excluded, and the integration originator also differed from a default Codex client. The observation therefore cannot isolate a client-version effect or attribute the native HTTP 400 to version, auth, routing, or wire construction. Raw private AppServer stderr and owner databases/auth files are excluded from the snapshot. [CATALOG]

## Standalone integration remains a separate gate

The first standalone invocation failed while parsing `set working-directory := justfile_directory()` in a constant context. After its narrow recipe correction, the next invocation failed Cargo resolution: the original Codex dependency required `rmcp =3.1.3`, while the Runtime dependency required `rmcp ^3.1.4`. Neither invocation reached its Rust tests. These failures motivate a separately reviewed process boundary, while preserving the original dependency constraints. They do not demonstrate that the revised process-port implementation has compiled, passed its tests, or completed a live provider round. [STANDALONE]

## Evidence custody and reproduction

The original archive holds 95 files (838,857 bytes before compression) plus its exact 18,980-byte manifest. The auxiliary archive holds nine existing review/raw bundles plus their manifest. Their full hashes and member manifests are pinned in [ARCHIVE_MANIFEST.json](ARCHIVE_MANIFEST.json). [RAW_CUSTODY.md](RAW_CUSTODY.md) records the custody stage; remote readback must be recorded separately after archive publication.

`python verify_archives.py` verifies both compressed files, regular safe member paths, duplicate exclusion, original manifests, and every direct member's byte count/hash. It reads evidence only and does not execute archived scripts, reproduce the tests, load models, read auth files, or contact a provider. The original logs, JUnit, JSON, raw canary bundles, and syscall captures must retain their bytes; formatting and spelling corrections apply only to new report prose/code.

The published science results remain separate: [Cell V4 results #3942](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3942), [fresh NDU preregistration #3943](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3943), and [fresh NDU results #3974](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3974). This engineering PR does not duplicate their raw evidence or turn their unresolved/negative comparisons into positive intelligence claims.
