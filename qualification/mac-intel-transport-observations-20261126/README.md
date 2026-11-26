# Intel macOS transport timeout observations

This candidate adds test diagnostics. It does not repair or qualify a transport,
and it does not establish a shared cause for the three failing targets.

## Original evidence

The complete failed-test logs came from the Intel macOS run of source
`97ab00451799667faebac2c455a1e3176ebc90cb`, job `139620849667`, artifact
`15079144917`. Each target has one retained failed attempt in that artifact.
Repeated console excerpts are not additional executions.

| Target | Original outcome | Complete log SHA-256 |
| --- | --- | --- |
| `exec-server-capability_discovery-test` | 3 passed, 1 failed; 6.71 seconds | `0fd38b5824bde666a3b071940692a795e3aed4c31e541da1243f8aaedf10d86c` |
| `exec-server-forward-test` | 0 passed, 1 failed; 35.21 seconds | `b8cf9532aee552970286c5bda3960021ba08a06ef7e016880d9bdb16b10b3ff4` |
| `rmcp-client-streamable_http_recovery-test` | 9 passed, 4 failed; 15.40 seconds | `c918159e01d47c5bda8491a10d1ee255d83f82616f12f6b8cb92992aeedfc57f` |

The capability-discovery failure reports an existing WebSocket event deadline,
without identifying initialization or either permissions batch. The forwarder
reports an elapsed deadline without identifying command execution, output,
the oversized file write, or shutdown. The four HTTP cases fail while creating
and initializing their clients, before their 401, 403, or 404 fault controls are
armed. Their recovery assertions were not reached.

The existing HTTP fixture already waits for a successful TCP connection and
checks whether the child exited. The current evidence does not prove that a
missing readiness check, a port-allocation race, or the HTTP recovery policy
caused these failures.

## Added observations

The two exec-server tests add fixed phase context to existing error paths. They
retain the original error as a cause. The WebSocket harness, relay startup,
permissions, 13 MiB transfer, encrypted-frame checks, deadlines, and assertions
are unchanged.

The shared HTTP fixture delegates through a per-client observer that retains
eight fixed-size atomics. It counts entry into the existing buffered and
streamed HTTP futures, successful returns, errors, and the last observed HTTP
status for each method. The streamed success counter means response headers
and the original body-stream handle returned; it does not mean the body was
read or the MCP handshake completed. No response stream is consumed or wrapped.

Only a failed client construction or initialization formats the counters. These
are independently read observations, not a coherent snapshot, a wire trace,
or proof that another task cannot subsequently finish. Entered calls that are
cancelled need not produce a success or error counter. A zero counter means
that this wrapper has not observed that future being entered; it does not
prove that a server or unrelated transport was idle. No URL, request headers,
body, credentials, process output, or process-global subscriber is captured.

Each wrapper invokes the supplied client exactly once per method call, awaits
that existing future, and returns its original result and body-stream handle.
No new HTTP request, retry, deadline, sleep, readiness probe, global state, or
production API is added. The existing five-second initialization policy and
all existing recovery tests remain unchanged. The observer uses existing
crate dependencies, and its nested source is covered by the existing Bazel
`tests/**` compile-data glob without adding another test binary.

## Qualification boundary

Only source review, formatting, and static preservation checks have run for
this candidate. No Rust compilation, native execution, or new CI run is claimed.
The next normal qualification must retain the complete discovery, forwarder,
and Streamable HTTP recovery targets, their original timeouts and retries, and
the original initial failures. A more informative error is not a passing test.
