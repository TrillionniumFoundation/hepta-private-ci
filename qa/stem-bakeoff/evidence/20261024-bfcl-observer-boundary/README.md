# First-query structural boundary: not a working BFCL observer

This reviewed component validates a narrow already-constructed request. It does not produce observations from tasks, capture a real handler, train a model, execute a tool or evaluate a task. Read DESIGN.md before using it.

Run the16 synthetic tests with the standard library:

    python -m unittest discover -s . -p test_boundary.py -v

No upstream source is required for these tests. To independently verify the design's source interpretation, acquire the five official files listed in upstream-manifest.json at its exact pin and check their hashes. Those129928 bytes of upstream code are deliberately not bundled or executed here.

## Review corrections preserved

The first version incorrectly permitted a dictionary in numeric JSON Schema minimum, allowing {initial_config: SECRET_CANARY} through that structural position. Independent review found it before publication. The corrected version validates keyword value types; dedicated negative tests reject the original probe and related container/scalar cases. default/const/enum elements remain arbitrary visible JSON literals, explicitly not semantic DLP.

A second review correction limits response-schema rewriting to the actual upstream model-style branches. The selected OpenAI-completions handler can retain function.response, which this narrow validator explicitly rejects. It does not silently drop it and is not ready for BFCL ingestion. Caller-supplied pin/turn assertions are not authenticated capture provenance. Already-visible user text can contain a leak inserted upstream; the validator cannot detect that semantically and a test demonstrates this limitation.

The companion correction to the previous interface-audit report removes the unsupported assertion that excluded_function must filter offered tools. The inspected official loader handles missed_function, but no excluded_function filter was established in that source path. No replacement filtering rule is invented.

## Open real dependencies

A trusted captured request from the pinned official handler, generated under an approved environment lifecycle with outbound model calls disabled, is still missing. The current task did not authorize executing that environment. Exact schema support (including response), observer visibility, later-turn real assistant/tool histories and staged tools require genuine integration evidence. Later turns are rejected. A real Hepta action/argument/state adapter remains missing.

Do not turn these16 synthetic tests into16 task successes, a privacy guarantee, a model score or evidence that the full observer is integrated. This is not a resource-isolation boundary against hostile Python objects. No training or new labels are permitted by this artifact, and no remote CI was queried.
