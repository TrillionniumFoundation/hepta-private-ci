# Original local writer handoff qualification

Frozen source `9b133c5f2ebc97160f592fa32974b1f6be443c9d` passed the original
component scope54/54, 610 filtered. It uses actual Fleet transitions, original
protected factory, original SQLite/local lease owner, actual wall-clock lease
expiry and the complete Objective sender binding. Root signed-proof issuer and
checkpoint peer remain explicit fixtures; these tests do not qualify real Root
adoption, durable Root CAS, actual two-process recovery or native ELF execution.

The six source commits separate fixed process spawn generation from the local
lease's exact one-step generation, verify the live full Root process binding
before exposing a recovered writer, retain exact PermitIssued binding, and add
whole-owner Current acknowledgement without creating a ticket or send permission.
A legitimate Starting1 -> Failed2 -> Starting3 uses local lease generation2.
Before actual local expiry the factory still refuses; that attempted bind can
leave Root Dirty. Trusted launch must wait for legal release/actual expiry first.
Unknown publication permanently fences the whole owner and never authorizes a
retry, changed cut or effect replay.

Original v1 failed one new assertion after52 passes because its wrapper error
was overconstrained; v2 failed compilation because SQLx0.9 rejected dynamic SQL
in trigger restoration. Both attempts are retained. The correction uses the
original static migration DDL and asserts exact schema equality. Final scoped
just fix passed without a source change. Original just fmt and the explicit
`just fmt --base 22010a8c03 --check` both passed; the latter covers all12 changed
Rust files. HEAD, staged and unstaged diffs remain unchanged. No tests followed
finish. The original logs and stage evidence remain in [the manifest](publication.json).
