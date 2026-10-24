# Pinned first-query boundary validator, not a BFCL observation generator

## Verified source path

Official pin6ea57973c7a6097fd7c5915698c54c17c5b1b6c8. Five read-only source files,129928 bytes, exact Git blob+SHA256 receipts in upstream-manifest.json. No upstream code was imported or executed.

- bfcl_eval/utils.py:771–802 populates schemas from involved classes and removes missed_function schemas until later release. It does not implement excluded_function filtering in this inspected path. Earlier interface-audit wording asserting such filtering has been corrected locally; no invented exclusion rule is implemented here.
- model_handler/base_handler.py:95–220 initializes backend instances even before the first query. It records state_info separately from inference_data, builds tools, and loops through user turns. When held-out tools are restored it recompiles schemas and inserts an official user message. Later assistant messages/tool execution results are appended; a simple question prefix is not the real later-turn context.
- api_inference/openai_completion.py:79–107 builds the actual OpenAI FC request from inference_data.message and inference_data.tools, plus model/temperature/store. Initial messages start empty and the first user-message block is extended verbatim (130–142). Tool results are associated with call IDs (152–169).
- model_handler/utils.py:35–218 converts parameter types and relevant function names. The response-schema-to-description branch applies to certain OTHER model styles, not OPENAI_COMPLETIONS. For the chosen OpenAI FC handler, response can remain on the function object. The current conservative boundary rejects that response field rather than transforming it. Thus it may reject current official tools; it is not a ready BFCL ingestion adapter. Raw function documents still differ from converted parameters.
- multi_turn_utils.py initializes classes, loads scenario states and later executes calls. We do not invoke it under this read-only task.

Official source URLs resolve by path under https://github.com/ShishirPatil/gorilla/tree/6ea57973c7a6097fd7c5915698c54c17c5b1b6c8/berkeley-function-call-leaderboard . Exact paths and hashes are in the manifest.

## Implemented scope

boundary.py accepts ONLY a request already constructed by that pinned OpenAI-completions FC handler at first turn/first step, using caller-asserted indices0/0. It does not read raw tasks, assemble tools, execute initialization, insert prompts, load initial_config, recover future messages or map Hepta labels. No genuine BFCL request has been captured. The pin/index arguments express a required caller contract, not authenticated provenance.

Payload allowlist is messages plus nonempty tools. Supported messages are text-only user messages with exactly role/content; system, assistant, tool, state_info and extra message fields reject. Tool wrappers/functions/schema nodes use explicit accepted fields; unknown fields reject rather than silently invent a compatible view. This deliberately supports only a narrow schema subset and may reject legitimate more complex official requests. Acceptance does not prove full JSON Schema validity or parity with all handlers. Transport model/temperature/store are not predictor features and are omitted.

Privileged raw-task fields (path, initial_config, missed_function, ground_truth, question, id, state_info and similar extras) reject at the envelope or unexpected structural locations. A schema property genuinely named path is preserved: blindly removing every nested key named path would corrupt legitimate tool semantics. Schema keyword value types are checked: invalid numeric/string/boolean/type containers reject. default/const and enum members are arbitrary already-visible JSON literals, not recursively interpreted schemas. Human text descriptions/defaults are preserved as already-visible content, not scanned for semantic secrets. Thus the validator is NOT a semantic leakage detector: privileged information wrongly inserted upstream into legitimate message text could pass. A negative test deliberately demonstrates this boundary limitation.

A separate sidecar helper holds source ID/group/digest metadata, with no path to merge it into the exported payload. It also does not prove provenance. A real recorder must create sidecar and payload separately and compute its digest from canonical captured bytes; that recorder remains unimplemented. Avoid passing combined dictionaries to a predictor.

## Tests and limits

Sixteen synthetic unit tests pass: allowlist fidelity; forbidden envelope/message/tool metadata; legitimate schema-property path; rejecting later rounds/steps/other pin; role restrictions; copy isolation; separate sidecar; empty tool omission; nonfinite/duplicate/unrecognized schema rejection; and explicit inability to detect a secret already in allowed text. These are synthetic canary/boundary tests, not natural-task outcomes, model scores or evidence of real capture parity.

No full-runtime pure payload extraction was executed. Although the request kwargs construction is simple, the actual first-turn tool construction/provenance occurs after upstream initialization, and later views depend on live model/tool outputs. We will not create a static approximation and label it a true observation.

## Open prerequisites before any training or evaluation

1. Trusted capture at the actual request boundary, plus source/handler pin and ordered-event evidence, with model call disabled and environment execution separately authorized.
2. Confirm exact supported categories and schema features; compare capture bytes with allowed export without changing actual visible content. Unsupported variants remain rejected, not silently clipped.
3. For later turns, design a separate adapter preserving actual assistant/tool history, tool IDs, staged availability and state visibility. Current code rejects these.
4. Integrate a genuine semantic Hepta adapter without relabeling absent operations or exposing construction metadata. Preserve group lineage and future audit independence.

Training, model scoring, official environment execution, external API calls and CI remain paused. This artifact closes only a small structural boundary-testing step.

Independent review found and we fixed an illegal schema-keyword container bypass: minimum={initial_config:...} previously passed. The corrected validator checks keyword value types and adds container/scalar/literal-boundary tests. This is an engineering correction, not a natural-task result.
