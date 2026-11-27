# Oversized forward-write failure observation

The retained Intel output reached the oversized file-write deadline after
the two command-output and exit-code controls. It does not show whether
the request reached the destination or whether the destination wrote the
file. The later full-content readback and encrypted-frame assertions were
not reached. No particular stalled hop or CPU cost follows from that
output.

The fixture still sends 13 MiB of original bytes, whose base64 form
exceeds the destination's 16 MiB frame limit. Its 30-second deadline,
request, relay forwarding and capture path, subsequent complete-message
readback, byte equality and encryption assertions remain unchanged.

Only the original outer write-timeout error adds a progress snapshot to
its context. The existing elapsed error stays in the chain. Successful
writes and inner RPC errors do not invoke this diagnostic. There is no
new timer, await, retry, filesystem probe or subprocess.

The snapshot reads the two existing task completion flags and attempts
the existing capture mutex once without waiting. If the lock is busy or
poisoned, it reports that state without treating missing counters as zero.
With the lock available, it reports the total captured frame count and
the count and byte lengths of at most the last 64 frames. It does not
decode, copy, print or traverse payload bytes. The sum uses saturating
arithmetic. Output contains only fixed labels, states and scalar values.

Captured frames include both directions and all earlier setup and command
traffic. Capture precedes the proxy's send, so a recorded frame does not
prove delivery to the other endpoint. The bounded tail byte count is not
the whole transfer size. The flags and capture snapshot are separate
observations; a task marked unfinished may finish later. These fields do
not identify a specific blocked hop or establish task success.

The existing capture and production forwarding code are unchanged. This
diagnostic does not claim to repair the timeout. It has not been compiled
or exercised in a new native run; the next normal qualification run must
still satisfy all original transfer and content assertions.
