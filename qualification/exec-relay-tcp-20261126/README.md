# Configure the owned relay fixture for immediate TCP writes

## Observed failure

The original `be271dd` forward integration test failed on both hosted Mac
architectures at `forward fixture: oversized file write deadline`. The Intel job
is `139664083831` and the ARM job is `139664083934`. Their original full job logs
and original artifact ZIPs are retained. Each forward target has one failing
case, with the original 30-second deadline; the following file read is not
reached.

The test sends 13 MiB of data, encoded as more than 16 MiB of JSON. The Noise
transport sends bounded 60 KiB plaintext records, and the forwarder preserves
the destination's frame limit with 8 MiB WebSocket fragments. Production relay
connections and the destination connector explicitly enable `TCP_NODELAY`.
The owned fake rendezvous accepted its TCP sockets with the default option.

## Candidate

Enable `TCP_NODELAY` on the already accepted owned fixture socket before the
existing WebSocket handshake. A configuration error propagates immediately.
This applies to callers of the shared fake-rendezvous helper, including relay
reconnect and version-skew fixtures. The separate accepted-WebSocket helper and
all production transports remain unchanged.

The existing end-to-end test remains the behavior check: its full payload,
fragmentation boundary, following request, exact byte comparison, encrypted
frame assertion, shutdown, and all original deadlines are unchanged. This
candidate adds no test iteration, sleep, retry, alternate result, dependency,
permission, or relaxed timeout. No socket option is silently ignored.

Tokio's pinned 1.54.1 TCP stream source documents that this option disables
Nagle buffering. The official full source and its license are pinned in the
private evidence package. The relevant production connector calls are also
pinned to the original repository source.

The old logs do not contain per-record timings or an observed socket-option
value. They establish the failing stage, not Nagle as its proven cause.
Scheduling pressure, crypto work, and another transport stall remain possible.
This is a narrow fixture-configuration candidate; actual native completion
under the unchanged test is still required. A later pass alone does not prove
an isolated timing cause across different hosted runs. No native execution is
claimed by this source change.
