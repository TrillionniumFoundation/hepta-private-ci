# ACT3 stage 5: browser adapter and mandatory execution gate

**Implementation delivered; actual browser qualification is NOT_RUN locally.**

The adapter drives real Playwright form fills/clicks on an isolated controlled
page. A loopback HTTP owner publishes the actual filesystem effects, and the
scorer reads physical owner bytes independently of DOM success. Two wire schemas,
post-commit socket-drop ACK loss, partial precommit failure, opaque observations,
same-invocation retries and changed-intent rejection are covered by executable
tests. Browser, HTTP, DOM, owner, setup/cleanup and wall counters are retained.

The cloud's existing Chromium was actually attempted and failed with `socket()
failed: Operation not permitted`; `browser-probe.json` retains the result.
The CLI exits 2 with `NOT_RUN` instead of treating an unavailable browser as a
pass. HeptaRuntime Mac inventory/reconciliation requests also timed out without
a durable job identity; that does not establish whether Mac dependencies exist.

The hosted workflow installs pinned Playwright/Chromium and must first pass the
non-skipping browser CLI before running tests and the complete frozen model
panel. Its status must be read on the exact source, separately from local source
compilation. A skipped unittest or successful filesystem run grants no browser
qualification.

The shared campaign now explicitly rejects duplicate/incomplete identity grids,
writes `ENGINEERING_FAIL` for unsafe results, and preserves raw physical state
when an episode errors after a real effect. Two actual failure-boundary tests
pass. Its updated filesystem campaign separately completed 384 episodes and
retained-byte audit; this does not substitute for browser evidence.

This uses a controlled loopback page, not an open website or a production user
task. Production authority, independent trust domains, policy benefit and
adoption remain HOLD. Fixed skills remain the reference.
