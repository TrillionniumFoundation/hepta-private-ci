# Private TMP roots fixture qualification

The original sandbox regression failed under a private 0077 temp layout because
its script changes its TMPDIR alias and writes to a redirected temp registry,
but the parent permission fixture granted writes only to the nested workspace.
The fixture now grants exactly four private roots: the original working directory,
real temp, redirected temp, and a separate alias parent. The enclosing repository
and shared parent receive no new write authority. Product policy is unchanged.

Source `db896f452659b62f1e52c063ad01fb0ed5cd54b7` preserves the complete original
script, execution environment and subsequent assertions byte-for-byte. The actual
bubblewrap case changed from one failure to one pass, with no skip diagnostic;
the original Linux sandbox package then passed 146/146, zero skips, in 5.850s.
Scoped fix and formatting passed, final diff equals the tested diff, and no tests
ran after that style phase. This is Linux host fixture evidence, not a composed
Rust1.96 workspace or native Asterinas result.

[Original receipt and log manifest](publication.json) retains the failed baseline,
source inputs and passing runs.
