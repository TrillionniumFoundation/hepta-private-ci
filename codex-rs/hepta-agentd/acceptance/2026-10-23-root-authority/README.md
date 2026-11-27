# Root authority acceptance, 2026-10-23

Each publication retains the original receipt, exact source identity, tracked
input hashes and logs. Compressed files decompress to the recorded raw SHA256.
Private keys, qualification disks, build targets and executables are excluded.
Source-specific successes do not qualify a later composed tree.

| Execution | Actual result | Scope |
| --- | --- | --- |
| [Checkpoint 01](checkpoint-01/publication.json) | Five passed, one new race-fixture failed | Actual Root/data and fresh original CognitiveStore anchors; the fixture incorrectly required only Conflict when the higher request sequence can win. Failure retained. |
| [Checkpoint 02](checkpoint-02/publication.json) | Seven passed | Correct definite pre-write busy-lock refusal, exact winning head, disappearance/restoration permanently fences the same object. |
| [Checkpoint 03](checkpoint-03/publication.json) | Seven passed, 5.443s | Source `3f023c18717a578d1beb9027eb61919b5f2ba4be`; original durable CAS already syncs and reads back under its publication lock. Removed redundant public reload after that success. All tracked inputs unchanged. |
| [Checkpoint finish](checkpoint-finish/publication.json) | Original scoped just fix and just fmt exited zero, empty source diff | Performed after semantic tests; no tests repeated afterward in the same phase. |
| [Original four owning packages](owning-aggregate-03fc-failed/publication.json) | 1,068 executed: 1,061 passed, one failed, six timed out; 26 skipped, one passed on the original retry | Source `03fcfdcd347a7125e3f7dd77f083baa0543cda80`; original test entry and deadlines unchanged. Supervisor read timeout plus six original deadline failures remain open. |

Checkpoint tests use controlled clocks and qualification writer bindings while
exercising real root-protected files, fresh SQLite anchors and durable CAS.
They do not qualify the real transport, trusted bootstrap, live writer lease,
power loss or production effect recovery. The composed service must attach the
backend behind the original peer, dispatch fence and deadline checks and pass
its own integration acceptance.
