# Exact 6318 compiler termination

This candidate contains b26 plus the narrow 35c0a12 compiler fix. The source was clean and identical before and after the attempt. The same-source helper build failed after 181.14 seconds: Cargo returned 101 because Agentd lib rustc received SIGKILL (signal 9). No new Rust type diagnostics appeared, but this is not a successful compile. Ordinary tests never started, and no fresh JUnit or UID0 result exists.

The post-exit memory and filesystem observation is included. The executor does not expose cgroup memory-event counters, so OOM is not established. No process cancellation was requested. Build concurrency was two, using the repository's original limited debug profile.

The archive also retains the exact candidate source bundle and source QA originals: RunStart 16 PASS; the single changed handoff case PASS; the entire historical-read module ran 12 tests with 25 subtest errors. These results are separate scopes. The later Root historical guard repair is not part of this candidate.

Every archive member has a byte count and SHA-256 in `observation.json`; compression was round-trip checked. Complete positive, NoUpdate and daemon plus Root cold restart counts remain 0, 0 and 0.
