# Clean checkpoint adoption qualification

Frozen source `338bf7ed24cd9058e0368c34ead587094800a0b9` passed all 14
explicit Root tests through the original just/nextest entry with Rust1.96:
seven existing backend tests, six real retained-pidfd adoption and uncertainty
tests, and one concrete fresh Root head bound by the original CognitiveStore
checkpoint client. Test time was 16.665s (16.912s including runner overhead).
All tracked source bytes match before/after. Scoped fix245.891s and fmt0.216s
passed with an empty final diff. No tests followed the finish phase.

The predecessor `44ed833564f7f844b74f6b05b7a323b6dee63275` ran 14 tests:
12 passed and two failed after their original runner retries. One proved that
an actual durable post-CAS head could be mislabeled as a definite Conflict;
the other exercised the original client's rejection of fresh counter0. The
separate semantic correction publishes fresh global counter1 with local
mutation sequence0, and preserves every post-CAS clock/pidfd error as Unknown.
Neither issue was bypassed with artificial mutations or a relaxed assertion.

The tests use actual Root-protected files on /data, original SQLite coherent
anchors, actual UID60001 process lifetimes, retained pidfds and exact full-head
CAS/readback. Authorization bindings and the qualification verifier remain
explicit synthetic inputs. They do not prove real canonical issuer rotation,
the service wire, a complete two-generation writer, Dirty/Publishing recovery,
Root restart after losing its pidfd, reboot or physical power loss.

[The publication manifest](publication.json) records the complete original
results, source snapshots, compilation/test/finish logs and empty finish patch.
No authority keys or private fixture disk contents are included.
