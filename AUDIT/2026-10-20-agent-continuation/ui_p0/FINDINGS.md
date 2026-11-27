# PR #2885: bounded HTTP terminal diagnosis

Audit date: 2026-10-20 UTC. Owner: `/root/ui_p0`. Repository: `TrillionniumFoundation/hepta-private-ci`.

## Disposition

**The primary UI gate remains failed. No UI product patch, browser-pin change, assertion change, timeout extension, or remote mutation was made in this investigation.** The original six full product UI scenarios were not rerun. The evidence supports an upstream Chromium terminal-state bug, already fixed in Chromium source but absent from both the primary browser and the separately inspected Playwright 1.64.1 Chromium release. The repository already has an integrated diagnostic probe for this same defect.

A real loopback experiment executed 20 diagnostic cases using the unchanged, bounded Makepad HTTP reader and actual Chromium processes. The old browser reproduced a complete 503 body followed by native `ERR_ABORTED` twice without aborting the request's JavaScript controller. The pinned 157 diagnostic browser completed those two cases. Empty bodies completed and all deliberate abort, overflow and truncation controls rejected on both browsers. The experiment exited 0 because its expected red/fixed diagnostic assertions held; this is **not 20 product acceptance passes**.

Production posture remains **DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO**. Qualifying the primary browser and rerunning the unchanged source/base acceptance remain external handoff work.

## Exact source and original CI

| Identity | Value |
| --- | --- |
| PR | [#2885](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2885), open Draft when refreshed |
| Source branch | `agents/a00-ui-main-20261019` |
| Source commit | `89933fdc84ed1151f04609a1881ab24aaef119b4` |
| Source tree | `25b2a7b559549fba0d22fa7d62d78c76c13cd5ce` |
| Source parent | `43a638d4e25ebc5a8b06babcd1c75c9acac53179` |
| Observed main base | `f8c9419df6ddeb36ff8b522a50219981fb8d9345` |
| Observed GitHub synthetic merge | `c1a76c78972c82a6a1638d4331a1fb8ee6940473` |
| Original workflow's separately assembled base-merge commit | `a1411851e988155fe3ca45c70e7fc31fdc09dd5c` |
| UI workflow | [39253698771](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39253698771) |
| Source UI job | [118063553356](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39253698771/job/118063553356): failed; five cases passed, width-640 timeout case timed out |
| Base UI job | [118063553876](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39253698771/job/118063553876): passed, six cases |
| Local isolated worktree | `/workspace/scratch/e42bf1712d56/ui-work`, branch `agents/20261020/ui-http-terminal`, clean at source commit above |

The current synthetic merge is not substituted for the original workflow's tested merge commit. Source and base results are kept separate. Full Blocking, Windows, security and other independent failures are not closed by this UI investigation.

The original source artifact is `product-gateway-source-head-89933fdc84ed1151f04609a1881ab24aaef119b4`, artifact ID `12191530387`. Its binding identifies UI source `5b3ffd2bdcd76285cccd7602ab8a101f6034b4bfb7809fd8d6c5002fe6953efb`, manifest `026de9ca6037800af4df12c53aee250f700b4e20ead41fa8d68679b4324bf410`, original framework `110d268d041fc127ef58e1178bd8bc9dc7e96229d805e25026900d999a232762`, packaged framework `b70442ed46ab0663323a1d7debd5676cc1dc281ec57d0be2a86f81b9eec078fc`, and gateway binary `aab393cbd6a376267d08c6d0b19a17c959d1abf9be6d0382f38c5ec785273c9e`.

## Original failing request timeline

Times below are the original artifact's relative milliseconds, not wall-clock timestamps. Source: `raw-request-audit.json`, `apiDiagnostics.network` and `apiDiagnostics.waits`.

| Time (ms) | Request | Observation |
| --- | --- | --- |
| 13147.154 | `21200.21`, owner status | Deliberately held request starts |
| 18149.770 | `21200.22`, runtime | Next runtime request starts |
| 18149.806 | `21200.21` | Expected owner timeout cancellation, `ERR_ABORTED` |
| 18152.954 | `21200.22` | Runtime response: 503, `Content-Length: 79`, `Cache-Control: no-store` |
| 18152.966 | `21200.22` | CDP reports 79 response data bytes |
| 18153.487 | `21200.22` | Unexpected native `loadingFailed`, `net::ERR_ABORTED`, `canceled: true` |
| 18955.793 | runtime finished wait | `timeout-runtime.finished` starts; no completion record follows |

The runtime native failure preceded the `response.finished()` wait by **802.306 ms**. A later 90-second teardown cannot explain that earlier native terminal failure. The owner cancellation and the unexpected runtime cancellation are distinct requests and must remain distinct assertions. A complete body and a synthetic application callback do not establish a successful network terminal.

## Root cause and rejected repair

The official upstream issue is [Playwright #42742](https://github.com/microsoft/playwright/issues/42742), linked to [Chromium #568852319](https://issues.chromium.org/issues/568852319). The upstream maintainer linked [CL 8508456](https://chromium-review.googlesource.com/c/chromium/src/+/8508456), subsequently merged as commit `62473ad0f747e245e514c93e741bb8e168a2a207` at **2026-10-06 21:44:48 UTC**, main position `1712735`. The Gerrit response is retained in `chromium-8508456.json`.

In `ResponseBodyLoader::DelegatingBytesConsumer::OnStateChange`, the old implementation notified its client before latching a terminal result. Stream EOF can synchronously close `BodyStreamBuffer` and cancel the consumer while that consumer still appears active. A `no-store` response uses the direct consumer path. The upstream fix processes the terminal result before notifying the client, so reentrant cancellation of an already completed body does not misreport the underlying load. This source-level mechanism matches the original failure signature and the independently executed diagnostic. No C++ debugger stack or custom single-change Chromium rebuild was captured in this audit.

An initial Makepad-JavaScript hypothesis was rejected as a sufficient explanation of the ordinary UI callback path. Although JavaScript request cleanup occurs in `.finally`, the pinned Rust shim removes both the internal and public request-map entries **before** it emits a response or error to the UI. A normal subsequent Rust `http_cancel` returns without invoking JavaScript for that already removed public request. The isolated red control also reproduces the native failure with `controller.signal.aborted === false`. Consequently there is no evidence-backed reason to rearrange Makepad callback state or weaken cancellation fences in this task. Exact Rust source: [web_network.rs at 337566c](https://github.com/kevinaboos/makepad/blob/337566c8b25d47f7e4fff6a202157b65bf183330/platform/src/os/web/web_network.rs).

## Browser and source inclusion

| Role | Browser / tool | Runtime/source identity | Inclusion finding |
| --- | --- | --- | --- |
| Repository primary version; local red control | Playwright 1.63.0; Chrome 153.0.8010.12 | CDP revision `971a7443b0c9b0a9b2860529b33331b76077ec62` | Exact revision source lacks the terminal-state ordering fix; local positive control fails twice |
| Separately inspected released toolchain | Playwright 1.64.1; Chromium 156.0.8078.4, revision 1248 | [Official browser manifest](https://github.com/microsoft/playwright/blob/v1.64.1/packages/playwright-core/browsers.json); Chromium source tag `156.0.8078.4` | Exact tag source still lacks the ordering fix; this browser was not downloaded or executed |
| Existing repository diagnostic pin | Chrome Headless Shell 157.0.8099.0 | CDP revision `94bcda4759263b9a241f5008a68e753c2ebe3081` | Exact revision source contains the terminal fix; local positive control finishes twice; still `diagnosticOnly` |

Source comparisons use `third_party/blink/renderer/platform/loader/fetch/response_body_loader.cc` at the recorded browser revisions or release tag. Retained SHA256 values:

| Local evidence file | SHA256 |
| --- | --- |
| `browser-153-response-body-loader.cc` | `667ec6672e478ce6841cfeacdd1c09d0d560463ae461b9109beae962f5d9a037` |
| `browser-156-stable-response-body-loader.cc` | `667ec6672e478ce6841cfeacdd1c09d0d560463ae461b9109beae962f5d9a037` |
| `browser-157-response-body-loader.cc` | `979ce76e70424734af0539e1858345b2e000a422fba5d34170d4748364143047` |

The old local control used the official Chrome-for-Testing full Chrome archive, whereas the fixed local control used the repository's already pinned official headless-shell archive. Their runtime revisions were recorded, and executable contents were hashed. This is a bounded two-browser diagnostic, not a custom Chromium comparison differing in only one commit. The local binary hashes identify the local experiment; they do not reconstruct an unrecorded executable hash from the original GitHub job.

| Browser | Official archive bytes / SHA256 | Executable SHA256 |
| --- | --- | --- |
| 153.0.8010.12, linux64 `chrome-linux64.zip` | 195836009 / `8aac35011c18f6e2d10696154af89a5728ac2ddd6dc6fad24ffdf243c3fcfd5a` | `8c599d43aec53f2460a31ae2f4af6bd863f8258b34ff519564bc5d4726bfaa1e` |
| 157.0.8099.0, linux64 `chrome-headless-shell-linux64.zip` | 126501006 / `9541eafbc02f85e3ec0c24b05f8bbffe88094389949860681bf6055aef668d7b` | `37164bfc553db9c17e11bc19c291738a1179c5b13529ec6f20a39bd665e91be0` |

Both archives came from `https://storage.googleapis.com/chrome-for-testing-public/<version>/linux64/<archive>`. Full URLs, versions, CDP revisions and binary identities are retained in `browser-identities.json`. The initial standard Playwright CDN download returned invalid tiny archives and failed; using the official distribution for the same pinned version succeeded. The 157 installer was the existing repository `install-font-diagnostic-browser.py`, unchanged.

## Executed diagnostic and exact bounds

The standalone `reproduce-no-store.mjs` runs a real loopback HTTP server and two actual browser builds. It extracts the unchanged HTTP methods between `network_http_pump` and `js_network_ws_open` from the pinned Makepad `web.js`; callbacks terminate in a synthetic allocation/export sink. No Rust WASM UI, native gateway, real owner or device is exercised.

| Input identity | SHA256 / revision |
| --- | --- |
| Robrix revision | `f2208f16184e1b2d8307dc9f98375e47b1fcd677` |
| Makepad revision | `337566c8b25d47f7e4fff6a202157b65bf183330` |
| Exact upstream `web.js` | `0404897d76bbd81e2225ab62b2fde1c4832e34331706b94c4c00aa71640fe765` |
| Existing IME patch | `694a54d1087bd004456a49ff742f7ff94d46df4803ab52c96bc6898f41bf89d4` |
| `web.js` after existing IME patch | `f2decc893fc78e346e35e61fef83f136088005b04e9f901adffbf2a063a24646` |
| Exact HTTP method substring, 8198 bytes | `43030e8e2c971c73d79a0e4dd2e8129d0491c8627cc047573b444c0d91e71e88`; identical before and after existing IME patch |
| Executed probe | `a6b72b0b4b912e3f8d59f15f24c660f2303d52d8e0cd3d73cee6ddb03af3a801` |
| Complete 20-record output | `36930f89773b225d80a19f35e0bbb1a19f96ff92cfd1368e9be9792c42526147` |

The synthetic positive response is HTTP 503 with **86 bytes**, rather than the original product response's 79 bytes. The server writes six bytes, writes the rest 20 ms later, and separates EOF by another 20 ms. It retains `Cache-Control: no-store` and the actual incremental reader. The configured reader limit is 256 bytes. Two fresh-context repetitions cover each of five cases on each browser.

| Case | 153 baseline, two repetitions | 157 diagnostic, two repetitions |
| --- | --- | --- |
| Full 86-byte 503 stream | 0/2 strict completion; 2/2 native `ERR_ABORTED`; complete response callback; controller never aborted | 2/2 strict completion; complete response callback; controller never aborted |
| Empty 200 response | 2/2 strict completion | 2/2 strict completion |
| Overflow, 257 > 256 bytes | 2/2 application error and native request failure; controller aborted | 2/2 application error and native request failure; controller aborted |
| Truncated declared content length | 2/2 application error and native `ERR_CONTENT_LENGTH_MISMATCH` | 2/2 application error and native `ERR_CONTENT_LENGTH_MISMATCH` |
| Explicit active cancellation | 2/2 application error and native request failure | 2/2 application error and native request failure |

All 20 cases emitted exactly one application callback and ended with an empty request map. Playwright terminal events were filtered to the exact `/data` request; some auxiliary native CDP arrays also contain favicon events. The diagnostic's 2-second terminal deadline fails missing terminals; it never converts them into success. The standalone probe observes `requestfinished`/`requestfailed`; it does not itself invoke the original product's `response.finished()` assertion.

The experiment used Playwright 1.63.0 and ran with `node /workspace/scratch/e42bf1712d56/ui_p0/reproduce-no-store.mjs`. Both browser processes, all contexts and the loopback server closed when the process exited. No alternative unbounded `.arrayBuffer()`, `.json()`, cloning path, cache-policy relaxation, expected-cancel relabeling or arbitrary timeout increase was introduced.

## Existing repository coverage and deduplication decision

At source `89933fdc`, the repository already contains:

- `apps/hepta-control-ui/e2e/robrix-font-transport.spec.mjs`: real HTTP and the actual packaged SDK reader, explicitly synthetic export sink, bounded terminal controls, native request terminals and recorded manifest digest.
- `apps/hepta-control-ui/tools/font-transport-fixture.mjs`: separated-body/EOF server; complete, revalidated, truncated, explicit abort, declared-limit and streamed-limit controls, including negative controls under both cache modes.
- `apps/hepta-control-ui/playwright.font-diagnostic.config.mjs`: separate baseline/fixed diagnostic projects; primary acceptance imports neither this config nor its pin.
- `apps/hepta-control-ui/tools/install-font-diagnostic-browser.py` and `font-diagnostic-browser-identity.mjs`: fixed download identity and stronger live `/proc/<pid>/exe` file-descriptor hashing with PID checks.

The existing integrated probe has stronger package and browser binding than this standalone experiment. The new experiment adds independent execution, two repetitions, an empty-body control and a synthetic 503 payload, but does not justify a second maintained regression implementation. **Keep this probe and its output as audit evidence only; reuse the existing repository diagnostic in a future qualifying run.** No redundant product source/test file is proposed. A focused PR search for the 503 issue did not identify another newer product repair; the broader PR ownership inventory is delegated to the parent coordinator.

## Remaining qualification and handoff

The release dependency is concrete: a supported primary browser/toolchain must include Chromium CL 8508456, with its inclusion checked against the actual shipped revision and binary identity. Merely selecting Playwright 1.64.1 is insufficient according to the inspected Chromium 156 source. The existing 157 pin is for diagnosis and cannot silently become the primary acceptance browser.

After the responsible owner publishes/selects a supported fixed browser, an owner-reviewed pin change must be followed by the original unchanged six source UI scenarios, the six base-merge scenarios and required engine/platform/Blocking checks. Preserve real no-store transport, the bounded body reader, negative cancellation/overflow/truncation controls, request terminal assertions and artifact source binding. No result from this audit authorizes a merge, a reduced gate, model promotion, physical Cell Split, production routing or privileged FinalUse.

**Not run in this audit:** original full UI six-case source/base suites; rebuilt Rust WASM UI or native gateway; full browser-engine matrix; Windows/macOS targets; full Blocking, Bazel or security qualification. Passing original base evidence remains historical evidence for its own commit.

## Retained evidence and cleanup

| Evidence | Bytes | SHA256 |
| --- | --- | --- |
| `source-job.log` | 1470409 | `e98950ce731d776176a885d03f25f8149782ce8e563c9caa52f8727d0a3d4cba` |
| `ui-gateway-source.zip` | 2117670 | `e6dc4efc5dde4049e4f9084b9468e997e4bf4d6d30dcb247e1894eb12d5f3461` |
| `raw-request-audit.json` | 60563 | `61b70b66913ce7dffe00481c8015a3952dd670fa8efd5a3dd982ee5c8b76850b` |
| `ui-build-manifest.json` | 40152 | `026de9ca6037800af4df12c53aee250f700b4e20ead41fa8d68679b4324bf410` |
| `no-store-reproduction.json` | 24679 | `36930f89773b225d80a19f35e0bbb1a19f96ff92cfd1368e9be9792c42526147` |

All audit artifacts reside under `/workspace/scratch/e42bf1712d56/ui_p0/`; `evidence-summary.json` provides a machine-readable inventory and outcomes. The unrelated initial `ui-source-diagnostic.zip` is retained but is not evidence for the failed product request.

After parent authorization, both regenerable browser caches were purged. Ordinary directory deletion returned success and briefly released space, but subsequent tool calls restored the deleted files; this anomaly is recorded rather than treated as durable cleanup. After rechecking both binary digests and finding no executable/open-descriptor use in `/proc`, the 590 regular cache files were truncated to zero bytes. A separate subsequent call verified both cache trees contained zero content bytes and zero allocated file blocks; free space increased from about 491 MB to 1.190 GB. The remaining directory/zero-file placeholders avoid the observed deletion replay. `browser-cache-purge.json` records this final operation. Only these two regenerable official caches were touched; identity/download records, both original CI artifacts, original logs, source snapshots, the executed probe and all 20 result records were retained. Reproduction now requires reinstalling the exact distributions and must not attempt to run the empty cache placeholders.
