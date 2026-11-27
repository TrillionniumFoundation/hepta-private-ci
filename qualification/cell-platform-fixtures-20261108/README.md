# Platform fixture and lifecycle qualification

The shared source at f49128e503b24bb52ccdb32a860939e6392c8e08 failed actual macOS/Windows CI fixture paths. This follow-up fixes five test-only path/identity setups and gives two complete paired-process scenarios an explicit bounded native watchdog.

## Changes

- Resolve the existing temporary parent before creating the circuit store.
- Retain the canonical fleet path in the pre-kill recovery evidence.
- Resolve the test executable before release installation; the production non-symlink check remains unchanged.
- Use a short private Unix test root for the native worker control socket.
- Compare the typed SQLite corruption path with its canonical existing file.
- Run the two paired-process parent scenarios serially with no automatic retry and a six-minute total harness watchdog. All original per-operation deadlines, child-count, exact PID/generation, adoption, crash-isolation and shutdown assertions remain. The fixture now reports setup phases for future failure diagnosis.

## Actual execution

Thirteen selected library tests passed on the frozen initial candidate. The two-parent lifecycle run initially produced one pass and two 60-second timeouts under the repository's default retry. A separate serial run with retries disabled reproduced the same five-pair timeout and the two-pair pass. These attempts remain in the archive.

The final bounded run passed both parents: five pairs took 144.359 seconds and two pairs took 48.000 seconds. These measure complete native fixture scenarios; they do not establish a product latency objective. One ignored child-helper entry is invoked by its controlling parents. Repeated attempts are not additional unique passing tests.

The initial library test tree was dfb184209480f67b36838fb6e39708e987343b94; the complete lifecycle test tree was 7bbdf48705a64e295f7bea7ae653bd6f98a7a408. Official final formatting changed layout in two fixture files. No tests ran after formatting. The separately captured source hashes and patches identify the exact files executed.

Code publication commit: 083636159a1c2cf2570dfe6443c6210338fc5277. Formatted code tree: 8638fda7abffb4589fddad339e3905c5e1d6f660.

## Independent static review

A separate read-only review inspected the complete lifecycle candidate at tree 7bbdf48705a64e295f7bea7ae653bd6f98a7a408. It found no blocking change to the existing contracts:

- The nextest override selects only the two exact paired-process parent names, uses the existing one-thread group, disables retries and bounds each complete scenario to 360 seconds. The repository's local profile inherits that default override; the recorded command and configuration remain the execution evidence.
- Existing per-operation readiness/restart/replacement deadlines, warm-up and shutdown bounds remain unchanged. Exact PID/generation, all-ten-child adoption and crash-isolation assertions remain in the parent scenarios.
- The five fixture changes resolve existing filesystem identities or shorten the private Unix control-socket path. The short-path fixture remains inside its original Unix-only test. Production path validation is unchanged.

The comparison from that reviewed tree to code commit 083636159a1c2cf2570dfe6443c6210338fc5277 contains only line wrapping in native_app_server_tests.rs and paired_process_product.rs. The exact before/after hashes are retained in native/FORMATTING.json inside the original capsule. This static review is not an additional execution or a test of the formatted bytes.

There are 15 unique selected passing tests across the separately identified runs: 13 library tests on the initial candidate and two lifecycle parents on the complete candidate. The earlier three real timeout attempts remain failures of their recorded 60-second harness; the final 360-second harness result does not turn them into passes or establish a product performance objective.

## Evidence and limits

The capsule contains all seven original f491 failed CI job logs, original command outcomes and timeouts, patches, source identities, native stdout/stderr, formatting results and durable terminal process statuses. The requested shared-cache JUnit path was absent; no JUnit report is fabricated. Raw native results remain complete.

This is Linux native validation of these selected fixture behaviors. It does not claim macOS/Windows execution success or an overall green repository CI. The other observed Notes, Windows trust/lock, legacy sandbox and shell/forwarder failures retain their original scopes. Follow-up fixes are reviewed independently.

No source/model/data/budget owner or successor admission is created. All S0–S5 scientific gates remain HOLD.
