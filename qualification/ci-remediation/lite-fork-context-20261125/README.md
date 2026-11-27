# Lite full-fork context qualification

The source cut `fac3c71755e688edd7df3c2bd60a5739aeaa2c57` failed three
Windows full-history fork variants in job `139157914105`. The ordered matcher
reported that wire input 0 was an `additional_tools` item, whereas the child's
active context had no such item. The child completion barrier had completed.
The recorded variants were explicit model override, WorldState identity, and
restoring explicit delegation policy after a proactive transition. Original
failure output and retries remain in that job; this candidate does not claim
that the other variants received new execution coverage.

The production boundary is `ModelClient::build_responses_request` in
`codex-rs/core/src/client.rs`. When the selected model uses Responses Lite,
request construction prepends an `AdditionalTools` item, followed by a
nonempty `BaseInstructionsFragment`. It does this after formatting the prompt
history. Neither item is appended to the active conversation history. Matching
either against history confuses a request-only representation with stored
context. Non-Lite model-switching tests continue to use the original full
ordered matcher.

This candidate changes only tests and the existing cross-crate test-support
module:

- The read-only active-context snapshot also returns the completed child's
  actual base instructions. It neither replays history nor captures a new step.
- All six full-fork variants bind the prefix rule to their selected fixture
  model's effective Lite setting. For Lite, the outer `instructions` and `tools`
  fields must be absent. The sole `additional_tools` item must be first and have
  the exact developer-role envelope. The functions namespace must have its
  exact envelope and retain one custom `exec` and one function `wait` tool.
- A nonempty base-instructions item must immediately follow and match the
  child's actual text as a complete response-item JSON object. An empty base
  has no such prefix item. No arbitrary developer message is excluded.
- Every remaining wire item goes through the unchanged ordered exact matcher.
  Only response IDs and internal metadata are ignored for matching; the local
  annotations are retained for the original alignment and content-kind checks.
  An additional tools item anywhere else remains a failure. All role, policy,
  inherited-context, model, reasoning and WorldState assertions remain.

The integration fixture does **not** independently recover or compare the
complete step-local ToolRouter plan: no such read-only post-turn snapshot is
retained. The tools envelope and required leaves are explicit integration
checks, not a claim of complete tool-schema equality. The existing client unit
test now supplies a nonempty real `ToolSpec`, compares its complete converted
AdditionalTools JSON against a literal expected object, and checks unchanged
prompt history, tools and base instructions for both the official endpoint and
localhost metadata policies. Existing Responses Lite integration tests continue
to exercise the tool catalog and request representation.

`just fmt` and `git diff --check` passed locally. This candidate has not compiled
or executed the large Core graph locally. Its six fork variants and the amended
client unit require the original normal CI or the authorized warm Core graph;
no timeout, retry, skip condition, production permission rule or model setting
was changed.
