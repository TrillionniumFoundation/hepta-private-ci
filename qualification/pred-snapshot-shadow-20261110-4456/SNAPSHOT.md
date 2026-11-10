# PRED snapshot structural validation

Base: #5592, `218dac0f5009d1c4f1c1501a3bcc6d54dbe7b21a`.

A correct envelope checksum previously allowed an incomplete numerical snapshot
to reach the readback join. Both freezing and joining now use one structural
validator. It checks exact fields, native identity and collection digest,
clock/cursor and availability, ordered feature layout, finite bounded numerical
rows, event references and their visibility, and the final decision row.
Zero-event histories remain valid.

The scoped package passed **103 tests**, including two new behavioral tests
with malformed rehashed snapshots and invalid encoder structures. Actual SQLite
is used with synthetic owner rows. Repository `just fmt` and Ruff passed;
formatting preserved every tested AST. Validation/source receipts are adjacent.
The inherited Windows fixture byte correction is retained.

This validates stored structure, not that the claimed encoder produced the
numbers, that an owner/database is authentic, or that numerical action/candidate
IDs map to the native dispatch identity. Owner settlement is still separate
from business effects. No real owner, effect labels or new training was run.
Create-only file saving and reader reopen do not establish atomic publication,
directory fsync, or recovery after power loss. Initial-snapshot joins do not
chain every intermediate readback.

The historical 189-fit originals remain unlocated. No missing original receipt
or checkpoint was reconstructed, no old confirmation set reopened, and no
instability explanation, physical all-in cost or independent task gain claimed.
Qualification remains HOLD. Hosted CI must qualify this exact new source.
