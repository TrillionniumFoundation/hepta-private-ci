# CTRL protocol CI follow-through

This stage follows #5579 and preserves the sibling native CTRL stack. It adds an
exact-candidate workflow for the five protocol suites with non-skipped minima
6/6/8/4/5, original logs, source identity checks and failure propagation.

All 29 local protocol tests pass. The standard repository `just fmt` recipe
passes for the 12 unchanged CTRL Python files with actual Ruff 0.15.13. The first
offline synchronization failed because its wheel cache was absent. The successful
formatter attempt uses the exact-version binary already on PATH with uv syncing
disabled; this does not establish dependency installation or full-tree formatting.
Both attempts are recorded. The old Mac timeout is a separate retained failure.

The inherited spelling errors are a real domain and a research acronym; only
those lines are annotated. The HCSN workflow loses one terminal blank line, as in
sibling #5603/#5606. Neither change alters method, authority or runtime behavior.
The dedicated CI additionally checks the spelling annotations.

Protocol tests do not establish policy benefit, private native head training or
production admission. Full-repository native and platform failures remain distinct
from this bounded workflow. See CI_CLOSURE.json for exact scope and limitations.
