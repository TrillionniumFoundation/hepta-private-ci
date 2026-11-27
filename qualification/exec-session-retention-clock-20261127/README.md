# Separate transport resumption from retention expiry

The retained Intel unit output failed
`transport_disconnect_detaches_session_during_in_flight_read` while
resuming the first connection's session ID. The second initialize returned
`unknown session id`; it did not reach the same-session or processor-join
assertions. The source registry uses a 200 ms detached lifetime in test
builds and 30 seconds in production.

That transport control sleeps 25 ms after dropping the writer, then
creates another connection and resumes. A wall-clock sleep guarantees a
minimum delay. It does not guarantee that subsequent work is scheduled
before the registry's 200 ms deadline. The original log provides no
detach/resume timestamps and cannot identify a particular scheduling or
blocking cause.

Only this positive transport control selects an instance with a frozen
clock. Deadline creation, immediate resume expiry checks and background
expiry checks read that same instance clock. The field and constructor
exist only in test builds. Every normal registry still reads Tokio time.
Neither detached TTL is increased, and the original 25 ms delay, 5-second
read request, one-second completion bounds and all assertions remain.

Two separate controls use normal registries and paused Tokio time. They
create and detach real registry sessions, then exercise resume at 199 ms
and rejection at 200 ms. They test the existing deadline boundary through
the registry API rather than only comparing a clock value. Existing
active-session and long-poll resumption controls are unchanged.

The frozen clock has no advance operation. Its background timer may wake
on real time and find the instance deadline unexpired; it cannot remove
that transport fixture's session because real scheduling took longer.
This mode does not model timed retention and is not used by expiry
controls or production. Shutdown and connection ownership are unchanged.

The new controls have been authored but have not run. Static review and
formatting do not establish a native PASS. The original failure remains
recorded, and the next normal qualification run must exercise both
transport behavior and the independent expiry controls.
