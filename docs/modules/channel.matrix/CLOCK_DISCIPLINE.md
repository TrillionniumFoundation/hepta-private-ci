# channel.matrix clock discipline

The sender uses a monotonic `DispatchClock` anchored to the durable wall-clock
sample supplied at the start of one dispatch pass. Grant validity still uses the
more conservative of that monotonic-derived epoch and the current wall clock, so
a wall rollback cannot extend a grant.

`DispatchClock` separately captures the real wall clock at construction and
compares expected wall progress with later samples. A forward discontinuity over
5 seconds stops the sender with the existing fail-closed clock error before any
new adapter poll. A backward discontinuity over the same bound retains the
monotonic anchor and emits one diagnostic; it never rewinds durable time.

The identity-free event schema is:

```text
hepta.channel-matrix-clock-discontinuity.v1
```

It contains only direction, divergence, threshold, action and an explicit false
authority flag. Forward action is `sender_fail_closed`; backward action is
`retain_monotonic_anchor`. Operators must investigate host time, suspend/resume
and hypervisor/NTP behavior. Silently moving the clock back is not a recovery
procedure.

Process-fault scenario `MATRIX-PF17` remains a target-host gate: source tests
prove classification, not the actual host clock behavior or expiry-storm
response.
