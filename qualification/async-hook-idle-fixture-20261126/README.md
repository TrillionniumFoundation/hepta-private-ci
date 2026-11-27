# Idle async hook fixture scope

The idle-hook regression mounts exactly two model responses. The first prompt
launches a gated async hook; after that turn completes, the test releases the
hook and proves that its result remains quiet until the second prompt. That
second turn must receive the first prompt's buffered warning and context.

The original fixture also produced a new async result for the second prompt.
Because the release file already existed, that result could finish during the
second sampling request. The production post-sampling drain correctly adds such
new context to pending input and requests another sample. Five complete failure
logs contain a request with the second assistant response followed by this new
developer context, then HTTP 404 because the two-response mock is exhausted.
The sixth log contains the same completion timeout but no HTTP trace. The six
logs represent three attempts in each of two local Bazel invocations for one
test scenario; they are not six different regression cases.

The helper now accepts an optional exact prompt filter. The idle test selects
only its first prompt, before any marker, gate wait, warning, or context output.
Its second prompt still tests delivery of the buffered first result. The active
turn test keeps the unfiltered helper behavior. Production hook processing,
permission checks, the two model responses, 5-second deadlines, 150-millisecond
quiet interval, turn identity, warning identity, and context ordering assertions
are unchanged.

This is a fixture source correction. Static checks and direct execution of the
extracted Python fixture do not qualify the Rust integration tests. The existing
active-turn and idle-turn tests, followed by the hook suite under the repository's
normal test commands, remain the behavioral gate. No extra mock response, retry,
or longer timeout is introduced.
