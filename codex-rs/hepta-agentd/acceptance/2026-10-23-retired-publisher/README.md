# Same-boot retired publisher qualification

Frozen c54e11013209260fd0adeca2ca50e6071185f309 passed the original14 Root
checkpoint/client/adoption cases plus five new retirement cases:19/19 in62.747s,
zero retry,315 filtered, Rust1.96. All tracked source bytes match before/after.
Actual dedicated UID60001 children and Root/data CAS are used; authority values
remain explicit controlled fixtures.

The positive closes and reaps the old child, drops every original captured
pidfd and service object, independently observes actual kernel retirement, and
adopts only the exact protected Current into the captured live successor.
Other tests refuse the still-live original even with changed UID metadata,
a different boot, a nonmatching protected lifetime and Dirty/Publishing/Fenced.
Post-CAS clock failure remains Unknown while exact new-head readback is retained.
The invented-start-time case is a replacement-identity negative; it does not
claim the test forced actual PID reuse.

Original scoped fix221.498s and default fmt0.215s passed with an empty diff.
Because default fmt on a clean committed source selected no files, the same
finish explicitly ran original just fmt --base1a505bad0 (1.118s) and its range
check (0.416s), both successful. The exact35920-byte patch only reformats four
files, including earlier inherited adoption formatting. Finished leaf6199d3a9
is separate; no semantic tests were rerun after formatting.

The API is Root-only and non-deserializable. ESRCH, actual pidfd exit or a
live PID with a different actual start-time can prove an old lifetime ended.
UID drift and read/primitive failure cannot. The original trusted launcher's
fixed PID namespace remains a precondition. Every exact-cut, full receipt/CAS,
local lease succession, canonical authority and final uncertainty rule remains.
This does not qualify an actual whole Root process restart, cross-store proof
reconciliation, Dirty recovery, reboot, physical power loss or native service.

[Complete original snapshots, compilation/test/finish logs and format patch](publication.json)
retain each stage's exact source identity and scope.
