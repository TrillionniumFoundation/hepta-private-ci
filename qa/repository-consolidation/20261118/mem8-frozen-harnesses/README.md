# MEM8 frozen harness history

The five-case and V2 subagent harnesses retain their original plans and
branch-specific workflows. Their Python drivers and support modules use the
repository Ruff layout, applied by `just fmt`; complete executable ASTs remain
identical to the historical sources. The support files also lose two surplus
final blank lines. `MANIFEST.json` records both byte identities and the common
AST identity. The canonical Windows sandbox
lint harness uses the V11 frozen source. The original V10 and V11 have identical driver and
support bytes; their plans and workflows name different frozen source commits.

The complete V10 plan and workflow are retained under `v10/` with their Git blob
and SHA-256 identities in `MANIFEST.json`. These files are historical evidence;
the workflow copy is outside `.github/workflows` and is not active.

All plans remain `PREPARED_NOT_ADMITTED_NOT_RUN`. This consolidation did not run
native Windows tests or grant a new native, elevated, provider or production
qualification. V11's historical source-only record does not turn V10's dirty
source lint result into a pass. The original branch-specific workflow triggers
remain unchanged and do not trigger on main or pull requests.

The current audit checked the four complete four-file branch changes, exact
source commit and tree identities, all 92 declared source path and Git blob
bindings across the four plans, Python and YAML syntax, pinned actions, and
read-only workflow permissions. It exercised 18 JUnit identity and refusal
checks for the two native harnesses. Locally available source blobs also passed
length and SHA-256 verification; the remaining source content and historical
readback artifacts were not re-executed or independently regenerated.
