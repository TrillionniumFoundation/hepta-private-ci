# Ordinary tool and model-provider PQ boundary

Status: **OPEN — source audit, not a runtime qualification**.

This record checks the ordinary Agentd embedding at Hepta source
`1556a4df6e279055fd8196f81a4ca2fe0f19384a`. The automation HTTP/PoN
provider adapter and the ordinary model-inference FinalUse owner are separate
paths. Qualifying either of those paths does not close this one.

## Observed call chain

| Boundary | Exact source behavior | Consequence for the joint gate |
| --- | --- | --- |
| Agentd embedding | `hepta-agentd/src/app_runtime.rs` requests `features.hepta_governance=true`. | The normal Agentd route installs governance; this alone does not select PQ enforcement. |
| App Server composition | `app-server/src/extensions.rs` calls `codex_hepta_governance::install`. | The behavior below is reached through the ordinary composition, not only a test constructor. |
| Installation | `ext/hepta-governance/src/install.rs::install` selects `GovernanceMode::Shadow`. | Evidence and replay observations are not an enforced PQ owner capability. |
| Tool admission and authorization | `admission.rs::evaluate` constructs `GovernanceDecision::NotEvaluated` with the bootstrap integrity policy. `binding.rs::core_decision` allows NotEvaluated in either mode. | Changing the default enum to Enforce would not create root-signed authorization. |
| Generic dispatch | `core/src/tools/registry.rs` awaits admission, pre-tool hooks, and authorization before `handle_any_tool`; `lifecycle.rs` forwards inputs to the installed contributors. | A real gate exists at the dispatcher, but the observed Hepta contributor does not supply a current PQ grant there. |
| Model-provider invocation | `provider_policy.rs` records intent in Shadow, or claims durable intent and rejects pending/completed/indeterminate replays in Enforce. `provider_lease.rs` records terminal evidence. | The durable attempt lease is not a FinalUse PQ authority lease. |

The audited governance modules do not verify a signed per-effect FinalUse grant,
load the current PQ issuer/revocation roots, or consume a non-cloneable PQ use
token at the generic tool/provider boundary. Their bootstrap policy explicitly
covers payload digest and evidence integrity. This is a specific missing
authorization relationship, not a claim that every tool can bypass its other
approval, sandbox, provider, or network controls. Those controls remain in force
and are not substitutes for the requested PQ root trace.

The observed `ToolPolicyDecision` API carries Allow/Block, not an effect lease.
Any future owner bridge must bind the finalized tool payload, destination,
operation identity, current Agentd generation and current root, then revalidate
at the actual effect boundary after asynchronous waits. A pre-hook grant must
not silently authorize changed arguments. Cancellation and unknown outcomes
must retain the existing durable attempt and terminal rules.

## Scope and evidence

This is a finite source review. It does not establish a complete inventory of all
external sinks, prove an exploit, replace native tests, or qualify independent
root custody. No mode flip, approval bypass, root fabrication, or production
activation was performed for this finding. The joint all-sinks PQ gate remains
HOLD until an ordinary owner bridge and its actual effect-boundary controls are
implemented and qualified together with the other required sinks.

The adjacent `ordinary-tool-pq-source-inventory.json` records Git blob identities
for the files read. All links are pinned to the audited source. The HTTP/PoN
schema migration is tracked separately so its results cannot be reused here.

The separate [interface assessment](ordinary-pq-owner-interface-assessment.md) maps the existing one-shot ephemeral HTTP guard, its limited federation role, the missing WebSocket coverage, and the owner capability that must survive tool/provider waits. It is a source assessment; no new generic policy is installed.
