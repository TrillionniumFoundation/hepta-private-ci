# Exec forward relay progress observations

This diagnostic-only change extends the existing failure display of the test
relay. The oversized forward fixture, production transports and remote file
operations are unchanged. Its 13 MiB payload, 30-second deadline, real sends,
full readback and encryption assertions remain in place.

## Retained failure and mechanism evidence

The actual uncached ARM failure retained 213 captured binary messages; the later
Intel console failure retained 94. Even assigning every captured message the
maximum 60 KiB Noise chunk, neither count can contain the minimum 18,175,320
bytes of Base64 data for the complete request. This locates incomplete progress
at the test relay, but does not identify a cause or prove a deadlock. Console
timestamps are not internal phase timestamps.

The pinned send path flushes each message. Both upstream connectors and both
accepted relay sockets already request TCP_NODELAY. The retained Bazel settings
do not measure actual CPU use or uniquely explain the deadline. No transport,
socket option, parallelism limit, payload size or time budget is changed here.

## Observation contract

Each relay owns one progress object with fixed scalar atomics and one monotonic
origin. The relay task is its only writer. It records received and successfully
forwarded WebSocket messages separately for each direction; this includes
control messages and is distinct from the existing binary capture count.
Received increments after a successful stream item and before the original
capture. Forwarded increments only after the original send returns success.
These counters saturate instead of wrapping.

The forward-wait field names the direction surrounding that original send. A
small guard clears it on success, error or cancellation. A value of `none` does
not prove that the task is running or idle: it also covers waiting for input,
the unchanged capture step, task completion and cancellation. The age is measured
from the most recent successful send using the same monotonic origin. It is
absent until a successful send has been observed, and saturates at the integer
boundary.

Debug reads are independent observations, not one atomic snapshot. A direction
may be sampled before another field changes. Send success and its flush are not
peer acknowledgement, end-to-end delivery or successful file writing. The new
values cannot alone distinguish backpressure, starvation, socket stalls or a
deadlock; the causal defect remains open.

No payload, key, endpoint, message content or error string is retained in the
new object. There is no new lock, per-message allocation, payload copy or log
line. The existing capture and its nonblocking diagnostic read are unchanged.
The original abort/drop and connection shutdown paths are unchanged. The three
other direct relay callers supply independent default progress objects so the
shared helper has the same complete argument list in every test binary.

The compact failure display has a fixed scalar size, checked independently in
the source receipt; it is not a bound on formatting or output latency. No Rust
compilation or native test was run for this source candidate. The subsequent
normal CI run must qualify the new observation together with the existing tests.
