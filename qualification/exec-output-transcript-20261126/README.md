# Preserve the producer transcript for terminal output

Base: `b25482def1253d79be1529329f13c54eea2d5e94`.

The original musl attempt of
`suite::unified_exec::unified_exec_formats_large_output_summary` retained HEAD and
TAIL in the end event, but failed its byte-omission-marker assertion. The same
attempt's tool response reported 325,003 original tokens and the expected
251,434 omitted bytes for 1,300,010 input bytes. The event body and broadcast lag
counts were not recorded. This does not prove which scheduling path caused that
particular failure.

The source has two independent ways for the end event to see an incomplete
transcript: the delta subscriber can start after output was published or lag
behind its 64-message broadcast channel; and the short-lived-command path can
emit completion while the delta task is still accumulating output. A nonempty
partial transcript overrides the complete polling fallback.

This change records the existing bounded cumulative transcript in the same
producer paths that fill the polling buffer: local output, exec-server pushed
output, and exec-server read recovery. Each chunk reaches the transcript before
the polling buffer and broadcast. The delta consumer no longer owns a separate
transcript. Polling still drains only its own buffer. The two existing bounded
buffers retain their original capacities; there is no third cumulative buffer.
The two mutex guards are released separately, and no guard spans a notification,
event send, or the acquisition of the other mutex.

Two new channel-backed controls require downstream broadcast lag and late
subscription, while checking the complete cumulative bytes and real polling
drains. Existing UTF-8, delta quota, late-output, network-denial, and integration
assertions remain. Their setup is adjusted to use the producer-owned transcript;
no expected values or deadlines change. No dependency, lockfile, production
timeout, channel capacity, truncation policy, or event schema changes.

This is a source candidate until normal Rust CI executes it. It does not repair
or establish absence of loss in the earlier local PTY fan-out, and the existing
post-exit grace still bounds how long output is awaited. It is not a new model
forward, weight edit, training run, or end-to-end Hepta qualification.
