# MCP client conformance

This directory tests the actual Codex executable against the official Model
Context Protocol client conformance suite. It exercises the shipping legacy,
intermediate `2025-11-25`, and modern `2026-07-28` protocols, localhost HTTP,
stdio, OAuth, and additional transport and security regression fixtures.

The official upstream suite is pinned to
`modelcontextprotocol/conformance@49103de6ed70804e940637bf3e9e29e4a3f54e64`.
The reviewed OAuth-origin fixture is a four-source fork of that exact revision:
three launcher/producer changes and one component-test file. Its complete source
map and patch are recorded in `oauth-origin-fixture.json` and
`oauth-origin-fixture.patch`; the upstream checks and protocol modes are retained.
Use Node.js 22 and Python 3.11 or later for the fixture build.

## Run the conformance gate

The reviewed-fork receipt is produced by the original `blocking-ci` SDK job
after Root activates its source manifest. That job explicitly checks out the
event's source head and retains the provider's event SHA separately. For a pull
request, the source has the pinned B32 parent, and the actual event merge must
have the same tree and exactly the B32/source parents. A complete Git tree
reconstruction checks all source leaves and the exact twelve changed paths.

The existing Bazel step records the source before and after its original build,
then hashes both the original Bazel outputs and the staged Codex/code-mode-host
siblings. The later fixture and SDK consumers require the authenticated provider
record for that same run, first attempt, job, runner and current step, including
successful completion of the original build step. Environment values select
provider records; they are not accepted as standalone run or binary evidence.

Inside that original workflow, fixture preparation uses:

```bash
python3 scripts/mcp_conformance/prepare_oauth_fixture.py \
  --output "${RUNNER_TEMP}/hepta-oauth-origin-fixture" \
  --build-receipt "${RUNNER_TEMP}/hepta-sdk-original-build/RESULT.json"
```

The preparation command rejects an inactive manifest. It checks the exact upstream
commit and all 263 source leaves, applies only the reviewed four-path patch,
checks all 264 resulting leaves, installs the original npm lock with
`npm ci --ignore-scripts --no-audit --no-fund`, runs the original twelve local
Python controls plus nine candidate-identity/failure-retention controls and the
eight upstream component controls, and builds the CLI. Its receipt retains the
original commands, output, controls, source maps, lock and built CLI/chunk hashes.
Fixture preparation and both SDK consumers recheck the current source and actual
staged binary bytes before and after use; a receipt from another run, attempt or
job is rejected even when the source head is unchanged. A fixture build does not
establish OAuth or MCP conformance.

The fixture build keeps its 400-second command deadline and 420-second acceptance
deadline including retention. The SDK step remains eight minutes and the job
remains sixty minutes. Individual identity observations are capped at twenty
seconds within those existing deadlines; the reviewer shares its original
170-second child window across identity checks and the original reviewer process.
The conformance and reviewer Jest deadlines remain 300 and 180 seconds.
Failed work and its costs remain evidence.

Local experiments can still pass a supplied executable and an unmodified
official `--conformance-cli` without the reviewed-fork receipt. They do not qualify
as this original SDK execution. The reviewed fork's complete `dist` bytes and
source/lock are checked; successful `npm ci` does not individually qualify every
installed runtime dependency file. Final provider job/run terminal status and
artifact retention require independent review outside the running job.

## What the baseline means

`regression-baseline-v1.json` is a compact, reviewed snapshot of the upstream
revision, required protocol versions, HTTP and stdio transports, enabled modern
feature, OAuth coverage, and individual passing and failing check identities.

The gate exits successfully only when:

- The upstream suite and modern feature match the committed baseline.
- The shipping legacy, intermediate, and modern protocols are actually tested.
- The required HTTP, stdio, and authentication scenarios are actually run.
- Every previously passing check still passes.
- No additional check fails.

Existing known failures remain visible in the complete JSON report. In
particular, `success` describes complete upstream conformance and
`regressionGate.success` describes the no-new-regressions merge gate; the gate
does not relabel an existing failure as a pass.

Create a compact baseline from a reviewed complete report without contacting
the upstream suite again:

```bash
python3 scripts/mcp_conformance/run_codex_compliance.py \
  /absolute/path/to/codex \
  --baseline-report /absolute/path/to/full-conformance-report.json \
  --extract-baseline /tmp/mcp-conformance-regression-baseline-v1.json
```

Alternatively, add `--write-baseline /tmp/mcp-conformance-regression-baseline-v1.json`
to a complete conformance run. Review every baseline change; do not regenerate
it to conceal a regression.

## Run the production reviewer regression gate

The separate reviewer gate tests the real Codex app-server across all three
shipping, legacy, and modern protocol modes. It covers stdio and localhost
HTTP, exact-integer tool and elicitation schemas, bounded multi-round requests,
malformed discovery response IDs, repeated pagination cursors, SSE framing and
keepalives, and catalog boundaries. In a published Codex checkout, run:

```bash
python3 scripts/mcp_conformance/review_regressions.py \
  /absolute/path/to/codex \
  --mode all \
  --baseline-report scripts/mcp_conformance/review-regression-baseline-v1.json \
  --report /tmp/codex-mcp-review-regressions.json
```

A complete, main-derived baseline records all 186 real check identities and all
21 required cases. Existing failures remain explicitly visible in the complete
report; `regressionGate.success: true` means there are no newly failing or
missing checks. Improvements are recorded under `fixedChecks`. The gate never
classifies an existing failure as a passing check.

Extract a compact deterministic reviewer baseline from a reviewed complete
production report without rerunning the client:

```bash
python3 scripts/mcp_conformance/review_regressions.py \
  /absolute/path/to/codex \
  --baseline-report /absolute/path/to/full-review-regressions.json \
  --extract-baseline /tmp/review-regression-baseline-v1.json
```

Review every baseline update. Do not regenerate a baseline to hide a regression.

## Run the fixture self-tests

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  python3 -m pytest -q scripts/mcp_conformance
```

## Run the required SDK integration

The required SDK workflow builds the actual Codex executable, sets
`CODEX_EXEC_PATH`, builds and verifies the reviewed fixture, then runs both the
three-protocol authenticated suite and the separate production reviewer matrix.
Neither integration gate is skipped. The original test names, protocol matrices,
baselines and assertions are retained. The first gate verifies its fixture,
source and executable before and after conformance; the second performs the same
identity checks around the original reviewer.

The SDK caller job and reusable SDK job grant only `contents: read` and
`actions: read`. The job's token is used to read its current provider records;
there is no PAT or additional write permission. A missing, ambiguous, stale,
failed or cancelled prerequisite cannot be treated as successful identity proof.
The twenty-one local Python controls and eight upstream startup/sideband controls
have separate exact names and results. The broader pytest entry point above
remains distinct from that focused control roster.

## Exact OAuth authorization origins

The production default grants no additional authorization origin. An owner may
configure canonical HTTP(S) origins in a server's `oauth.authorization_origins`
array. The resource origin keeps its original handling; an additional origin is
an explicit destination grant, not permission to copy resource credentials.
Resource helper headers, bearer credentials and custom resource headers stay
scoped to the resource origin. OAuth Basic/Post/None credentials retain their
original request semantics. Redirect, issuer, address and ordinary-proxy
restrictions remain in force.

The reviewed test launcher sets `MCP_CONFORMANCE_AUTHORIZATION_ORIGINS` only from
the authorization server URL returned by the trusted scenario startup. It removes
inherited variants of that environment key and writes `[]` when startup supplies
no authorization server. PRM responses, metadata, scenario context and the current
request URL cannot grant an origin. The adapter validates that bounded sideband,
writes the owner config and removes the sideband before starting Codex. The three
token-authentication producers and four metadata-discovery producers supply their
own started authorization-server origins; other producers remain unchanged.

When a running MCP runtime publishes a changed configuration, replaced connection
generations with delegated origins are revoked before publication completes.
Retained old snapshots and prepared/retained calls do not renew that permission;
pending restricted requests and OAuth response consumption are cancelled and old
connections are shut down. Already dispatched remote effects cannot be rolled
back. Editing a file in another process alone does not publish a new configuration
to an existing process.
