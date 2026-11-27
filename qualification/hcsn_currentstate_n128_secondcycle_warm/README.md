# N128 generation-2 warm continuation

Status at source freeze: **HOLD / INTENT_NOT_EXECUTED**.

This separately frozen successor starts from the exact terminal `t=.2` capsule
published by Draft #6282, SHA-256
`833474bcdaf45c7787a2869fa86efbad2f8b22fdb0c88d0fbcbef1764f8a72a9`.
It does not rerun the already-qualified first cycle. It advances only the warm
lane to `.201/.28/.36`, including actual generation-2 packet release and the
coupled origin-1/origin-2 state.

The candidate continues the source-bound CSR graph. A separate dense decoder
and oracle parse the immutable #6282 container without importing candidate
implementation. All 1,731,278 coordinates are written as complete canonical
little-endian binary64 streams with an explicit coordinate schema, compared
coordinate by coordinate, and the three candidate capsules must survive
canonical dump/fresh-load/dump byte exactly.

An earlier unfrozen development probe that materialized dense coordinate lists
was killed with exit 137 and produced no result. Its cause and executed call
counts remain `UNKNOWN`; `DEVELOPMENT-RED.json` preserves that failure. After
removing the unbounded list materialization, a post-development local run
observed 1,731,278/1,731,278 bitwise-equal coordinates, 10 segments and 40
matrix exponentials per implementation. Neither local attempt is admission
evidence. Only the source-bound hosted attempt declared here can become evidence.

Even success does not qualify independent coarse/cold dynamics, third-cycle
release after `.4`, arbitrary histories, N256/N512 dynamics, full-network
training, finite-domain behavior, asynchronous complete cost, C2 full replay,
or HPCA external custody. All prior RED and `UNKNOWN` remain unchanged.
