# Startup Git enrichment fixture

The original startup case on source `4be2e45d4c90fe539abf61814fa9b362d8922881`
failed both normal nextest attempts (45.588 and 45.717 seconds). The complete
49-case regression log has SHA-256
`56e595a458a12dac2c73bcaa1b987c1c92852d402207300ef3f997105da65ca8`.
Both attempts recorded only connection 0/request 0, followed by the scripted
`response.created` and `response.completed`, then a request timeout,
reconnection errors, and the missing turn follow-up request. These logs do not
record the exact metadata difference at a connection replacement.

The fixture incorrectly required prewarm and both turn requests to use one
socket. The existing socket compatibility projection retains `workspaces`,
which asynchronous Git enrichment changes from an empty map to repository
metadata. The test server consumes all response batches for one connection
before accepting another handshake; waiting for another request on the old
socket can therefore block the compatible new connection.

Each of the three existing response batches now closes its own scripted
connection, as in the existing background-thread Git cases. The test requires
exactly one request on each of three connections and explicitly checks that
prewarm has `generate=false`. The full expected workspace object still binds
the repository path, origin URL, commit, and dirty state after the untracked
file is created. The original five-second prewarm deadline, 5000 ms tool wait,
shutdown, nextest timeout and retry settings are unchanged. Production socket
identity and recovery behavior are unchanged; this case qualifies Git
freshness, while the separate socket-reuse cases retain their own assertions.

Only formatting and source diff checks have run for this candidate. The real
startup case still requires the normal warm-source or CI execution.
