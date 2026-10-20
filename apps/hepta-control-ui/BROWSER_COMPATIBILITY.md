# Browser completion and the pinned Chromium dependency

The Linux browser qualification uses the official Chrome for Testing headless
shell **157.0.8099.0**. The Rust renderer, shared UI, SDK stream reader, API
`Cache-Control: no-store`, response limits, cancellation paths, and the original
six real gateway scenarios keep their existing behavior.

## Why this browser version is required

Chromium commit
[`62473ad0f747e245e514c93e741bb8e168a2a207`](https://github.com/chromium/chromium/commit/62473ad0f747e245e514c93e741bb8e168a2a207)
records a body loader's terminal state before notifying a client that can cancel
the loader. Without that ordering, an entirely consumed `no-store` response can
still produce a native aborted-request event. The SDK can have delivered the
complete response while the browser's completion audit remains unresolved.

The official tag
[`157.0.8099.0`](https://github.com/chromium/chromium/tree/157.0.8099.0)
points to `94bcda4759263b9a241f5008a68e753c2ebe3081`. Its verified Git comparison
with the fix has the fix itself as merge base, zero commits behind, and 3,731
commits ahead. Its `response_body_loader.cc` Git blob is
`40bc0f095e25466f0309cdc2513217a77d38270e` and contains the corrected ordering.
The versions checked on 2026-10-20, stable `155.0.8059.84` and Playwright 1.64.1's
bundled `156.0.8078.4`, still have the older loader source. Changing the npm
version alone would therefore not address this failure.

The official [Chrome for Testing channel record](https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions.json)
was rechecked at its `2026-10-20T10:18:26.692Z` timestamp. The stable loader is
[pinned to its release tag](https://github.com/chromium/chromium/blob/155.0.8059.84/third_party/blink/renderer/platform/loader/fetch/response_body_loader.cc).
Playwright's bundled version comes from its [1.64.1 browser manifest](https://github.com/microsoft/playwright/blob/v1.64.1/packages/playwright-core/browsers.json);
the fixed loader is [pinned to the verified 157 commit](https://github.com/chromium/chromium/blob/94bcda4759263b9a241f5008a68e753c2ebe3081/third_party/blink/renderer/platform/loader/fetch/response_body_loader.cc).

The existing installer retains its filename
`tools/install-font-diagnostic-browser.py`, because the optional font comparison
also consumes this browser. It now provides the same verified browser dependency
to the required Chromium projects. Firefox and WebKit remain the engines pinned
by Playwright 1.63.0.

| Input | Verified value |
| --- | --- |
| Archive | `https://storage.googleapis.com/chrome-for-testing-public/157.0.8099.0/linux64/chrome-headless-shell-linux64.zip` |
| Archive bytes | `126501006` |
| Archive SHA-256 | `9541eafbc02f85e3ec0c24b05f8bbffe88094389949860681bf6055aef668d7b` |
| Executable SHA-256 | `37164bfc553db9c17e11bc19c291738a1179c5b13529ec6f20a39bd665e91be0` |

These are observed vendor-download digests, not vendor signatures. Installation
also rejects redirected downloads, unsafe archive members, oversized archives,
symlink executables, and an existing destination. The configuration rejects a
missing or changed executable instead of falling back to bundled Chromium.
Every ordinary Chromium scenario records and verifies the running browser PID's
opened `/proc/<pid>/exe` handle, version, and upstream release revision. This is
test-process provenance and does not instrument the application or its SDK.

## Running the same qualification

Use a Linux x86-64 host with the project's original Rust and Node toolchains.
From this application directory, install the browser in a fresh task-owned
directory and set its explicit path:

```bash
npm ci --ignore-scripts --no-audit --no-fund
npx playwright install --with-deps chromium firefox webkit
TASK_BROWSER_PARENT=$(mktemp -d)
python3 tools/install-font-diagnostic-browser.py "$TASK_BROWSER_PARENT/chromium"
export HEPTA_CHROMIUM_EXECUTABLE="$TASK_BROWSER_PARENT/chromium/chrome-headless-shell-linux64/chrome-headless-shell"
npm run build
node tools/verify-http-boundaries.mjs
```

The original workflow runs the actual Rust renderer, six gateway scenarios,
fixture input cases, and pixel/OCR checks with their existing deadlines and
assertions. The new transport step runs after the ordinary gateway evidence is
saved and before the fixture build replaces the ordinary package. It is a
required step in both source and base-merge lanes. Its results and actual browser
identity are uploaded even on failure.

The transport driver is a new, reproducible reconstruction of the earlier local
boundary experiments. It does not claim to restore missing historical raw files.
It executes **60 required cases**: 20 scenarios repeated three times. They cover
fixed and split bodies, chunked bodies, zero-length responses, exact limits,
gzip decoding, the existing private font-delivery policy, HEAD responses,
declared and streamed overflow, truncated transfers, cancellation before headers
and before the final byte, the unchanged 20-second SDK stall timer, and an 8 MiB
burst. Another **36 hard negatives** exercise 24 bursts, six cancellations after
all but the last byte, and six HTTP URLs delivered through an HTTPS HTTP/2 proxy
with a false one-byte Content-Length. Three proxy bodies stay open until rejection;
three complete on the wire, preserving the completed-response framing counterexample.

Each successful response requires exact bytes and SHA-256, a native
`requestfinished` event, and a settled successful `response.finished()` before
page teardown. Incomplete, over-limit, and cancelled controls require one SDK error,
no exported response body, and a native failure. The three completed HTTP/2
counterexamples also require one SDK error and no exported body; their already
complete network transfer may finish before the SDK rejects the oversized body.
That outcome must have a real server finish, a native `requestfinished`, and a
settled successful `response.finished()`. It does not relax completion auditing
for any successful SDK response. API controls retain `no-store`.
The original request reader is extracted from the built manifest-verified SDK;
its entire method fragment is hash checked. No alternate reader, cloned body,
unbounded tee, or cache bypass is installed. The HTTP/2 proxy trusts only its
ephemeral fixture certificate's SPKI; it does not alter product TLS behavior.

The transport sink emulates WASM exports and **does not qualify Rust rendering
or actual gateway integration**. Those remain separate, mandatory original UI
jobs. The optional font diagnostic still explicitly runs bundled Chromium 153
and the fixed browser as separate diagnostic projects; its baseline cannot
inherit the required project's fixed executable. Both browser-path environment
variables must be set when running that optional configuration independently.

A green claim requires complete new CI receipts from the exact candidate head,
including both real UI lanes and all 96 transport controls. A source-level
upgrade or a passing synthetic transport run alone does not close that gate.
