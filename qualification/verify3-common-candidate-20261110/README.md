# Fixed VERIFY review candidate

This candidate combines maintained CI and the macOS path assertion from #5620,
the original remote OpenSSH diagnosis from #5630, the matched-analysis corrections
from #5623, and only the exact-checkpoint source/test changes from #5622. The
separate treatment journal is not installed into the dispatcher path.

All 48 maintained Python blobs equal their analysis-parent counterparts. Two
analysis modules are added, and the two checkpoint files are pinned to #5622.
SOURCE.json binds every composed Python file to its original Git blob and full
SHA256. INTEGRATION.json records the full source parents and selected paths.

Fresh local composition validation passed 170 tests, zero skips, the original
72/72 SQLite engineering rows and the controlled 9-scenario/17-subprocess dispatch.
These are engineering fixtures. No independent real-task or neural benefit trial
is added. Validation wall times are not complete physical costs or billing.

ENGINEERING.zip retains all 109 SQLite-output files, all 20 dispatch-output files,
and all 50 executed Python source bodies, under explicit relative archive paths.
The plain command logs retain stdout followed by stderr; they are not a merged
wall-clock event trace. RESULT.json records each command and original interval.
No state directory or source body is silently omitted from those three sets.
MANIFEST.json binds the evidence, except itself. The full repository formatter
failure and scoped Ruff check results remain in format-and-lint.json.

The inherited workflow checks out the reviewed PR head explicitly. This new head
must obtain its own three-platform, architecture and required CI outcomes.
Component PR passes were on synthetic merge checkouts and do not transfer to it.

Remote jobs cannot resolve ssh-keygen; the pinned image filesystem has not been
directly inspected. The diagnosis does not establish unique cause or a new image
digest. Cargo-deny's actual failure body also remains unavailable. Neither test
skips, advisory suppression nor unmeasured image pins are introduced.

Independent labels across dispositions, complete physical/historical cost, frozen
prospective error reduction, acceptable acceptance coverage and net utility remain
open. Scientific admission HOLD; production authority NONE. No merge or deployment.
