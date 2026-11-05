# Missing-marker fixture qualification

Source f4044f8d77b1c1142f84525b1b1f243e2ddf95d6 changes only the original
no-marker host-root fixture. A controlled private ancestor.git first made the
unchanged test fail, including its original two retries. The corrected fixture
configures one nonempty per-fixture unique absent marker. Ancestor discovery
still runs; an empty list is not used to disable it. Original root collection
and all final assertions remain byte-identical. Production default.git discovery
and the old full03 temp namespace were not changed.

The first correction failed because TOML Value IndexMut cannot insert a missing
key. That actual failure remains. The independent correction constructs the
normal map before ConfigLayerEntry. Original focused1/1 and owner175/175 passed
(2.654s owner summary), zero retry/skip, Rust1.95 on Linux. Scoped fix477.150s and
fmt0.378s passed. The recorded tested-to-finished diff only wraps the marker
expression. No tests followed fix/fmt; final commit bytes were not retested.

[Original logs, commands, inputs, tested/final diffs and source digests](publication.json)
retain both initial failures. The complete Linux a47 read chain was in this
scope; this does not qualify final Rust1.96 workspace, Asterinas or production.
