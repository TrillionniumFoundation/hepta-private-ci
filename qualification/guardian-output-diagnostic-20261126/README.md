# Retain the rejected fixture output

Base: `752eae654d24345b0999a5b151250a2a60dbcd8e`.

The two preserved GNU failure logs for
`guardian_receives_exact_trigger_for_single_network_request` contain repeated
fixture panics at the strict command-progress check, followed by the original
terminal-outcome failure. They do not contain the actual rejected tool-output
string. Those logs cannot establish which output form failed the predicate.

Only that existing failure path now adds the expected completion kind, the
first 80 Unicode scalar values of the output ID, the original output byte length,
and the first 1024 Unicode scalar values of the output. The unescaped output
prefix occupies at most 4096 UTF-8 bytes; Debug escaping can make the printed
representation longer. Formatting is bounded and occurs only after the unchanged
predicate returns `None`. It cannot convert any rejected output into success.

The strict progress parser, Guardian rationale, exact trigger assertion,
session checks, nine-poll maximum, original mock match counts, client retries,
timeouts, dependencies and production source remain byte-identical. No extra
request, poll, sleep, lock, clock, tool call or successful-path output is added.

Source inspection also rules out two proposed explanations for the ordinary
rejection path: deferred completion shares its result through `OnceCell`, and
central approval handling converts a Guardian `Denied` decision into
`ToolError::Rejected` before the network handler's invalid-decision branch.
Neither finding proves the actual cause of these native failures.

The original failures remain unresolved. This bounded diagnostic needs the
unchanged original tests in normal CI; static formatting and source checks do
not qualify native behavior or establish a production fix.
