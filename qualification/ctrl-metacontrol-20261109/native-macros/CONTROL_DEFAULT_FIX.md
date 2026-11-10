# Parse the effective native control profile

The native `ControlPlan` defaults omitted `memory_mode` to `reset`. The initial
macro collector checked the raw JSON field and incorrectly rejected that valid
profile before constructing an episode. Parse with the same actual `ControlPlan`
used by `EpisodeHost`, then require its effective memory mode to be `reset`.

The regression exercises omitted and explicit reset profiles, and rejects
persistent mode, booleans and null before output creation. Together with the
existing macro tests, 7/7 tests pass; owning Ruff formatting leaves both changed
Python files unchanged. This is a static/parser compatibility fix and fixture
validation. It does not establish what happened to a transport-timed-out native
request, and does not relabel any old remote request as failed or completed.

The original frozen native V3 files remain unchanged. A later native attempt
must use its own new source identity after the original request is reconciled.
