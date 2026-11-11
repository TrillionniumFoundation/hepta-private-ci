# Protected clock window qualification

Source `efadc8f1a67512f9dfc89eb4db9223845b441f62` passed the complete original
contracts package 227/227 in 35.114s, followed by five explicit Root clock tests
in 5.031s, using Rust1.96, original just/nextest commands and unchanged limits.
All tracked source bytes match before/after. Scoped fix36.715s and fmt0.215s
passed with an empty source diff; no subsequent style-only retesting occurred.

Actual protected-store cases cover complete repeated reads inside the durable
window without CAS, explicit projection refresh with CAS, a load blocked across
its old ceiling returning only newly durable post-load time, and corrupted clock
state refused without renewal or genesis. The original delayed-CAS window and
original expired FinalUse entry negatives remain: their fixture waits past its
already durable window before pausing the required renewal. It retains the
original delay beyond the new ceiling and the original five-second grant expiry.

These root fixtures use the original /run layout to control acknowledgement
delay. They prove the clock/authority boundary, not disk power-loss persistence.
Native V2 on the earlier3a50 source failed the original500ms feed bound; this
scoped change needs a separate frozen build and original native acceptance.
[Original logs, complete source snapshots and finish records](publication.json)
retain nine byte-identical original members.
