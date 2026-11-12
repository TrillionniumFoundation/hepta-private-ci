# Ordinary-owner observations and the VERIFY study boundary

The prospective study APIs do not create a production observation producer,
an evaluator identity, or an effect capability. A host must connect its original
observations to the frozen study without changing the original owner's checks.

## Inspected native seams

The following inspection is pinned to
`c941a5f72ee4c5f6a1535c72082e077895d3bc80` (#6125). It is a separate source
lineage from this research candidate and does not establish a live deployment.

| Existing original caller | Available evidence | Meaning and limit |
| --- | --- | --- |
| `AgentdAutomationEffectHost::execute` and `automation_predispatch_export::observe` | Claimed step, original intent, owner sequence and dispatch fence before the existing FinalUse/dispatch path | Owner facts, with caller wall time and per-step sequence. The two owner reads are not an atomic shared observation cut. This is not a complete free-ACK view. |
| `AgentdNotesLiteralAdapter::prepare_bound` | The original `observe_document()` result before `prepare_original_literal`, including document identity, revision, content hash and pending-receipt state | Reuse this observation and original run/owner/policy binding. A later reread cannot be relabeled as the original decision input. |
| `notes_thread_tool::observe_original_reference` | Original retained operation, exact request identity and complete retained terminal receipt; separately, the current document readback | The historical operation receipt and current application state answer different questions. A current matching document does not prove which operation caused it. |
| Original Notes writer's `retained_notes_terminal_receipt` | Original append-only terminal event, rechecked against its operation, target, payload and authority | An application-owner property receipt. Missing receipts stay missing; this same-owner receipt is not independent business adjudication. |

Relevant inspected source:

- [Notes preparation](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c941a5f72ee4c5f6a1535c72082e077895d3bc80/codex-rs/hepta-agentd/src/notes_literal_adapter.rs)
- [Original Notes thread tools](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c941a5f72ee4c5f6a1535c72082e077895d3bc80/codex-rs/hepta-agentd/src/notes_thread_tool.rs)
- [Original Notes writer](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c941a5f72ee4c5f6a1535c72082e077895d3bc80/codex-rs/hepta-memory/src/production_notes_owner.rs)

## Required connection order

1. Freeze the actual task roster, target and horizon, policy/model identities,
   optional checker, opportunity design, cost roster and loss specification.
   Keep the original task/source group; creating additional policy IDs does not
   create independent tasks.
2. At the original owner's decision frontier, retain the full shared free view
   that already exists, including every available ACK. Project only that view
   into each policy's `Snapshot`. Retain the original bytes and acquisition
   cost; a matching projection digest alone cannot prove completeness.
3. Record the policies' predictions, reserve one original optional-check
   opportunity, and bind its consumption in each policy journal before that
   policy's choice or checker start. Record actual checker execution and its
   original reply separately from the offered opportunity. Missing/pending
   replies do not permit a new effect or a duplicate checker invocation.
4. Leave original permission, revocation, ownership, required property checking,
   dispatch fencing and terminal readback in the native owner. The learned risk
   and check-value estimates can select optional evidence but cannot satisfy or
   omit those requirements.
5. Retain the original host disposition, then obtain the fixed-horizon truth
   for every planned attempt, including rejection, interruption and UNKNOWN.
   Use the original evaluator's evidence and current host verifier. Application
   state, provider completion and independent business truth are separate
   targets. Do not supply an accepting verifier or a new trust key to fill a gap.
6. Join the original journals and disjoint measured cost receipts. A clean named
   target after rejection is not proof of an erroneous rejection: authority or
   other required obligations may still be unresolved. Missing resource measures
   and missing outcomes must remain visible in the declared utility result.

## Open field gates

This candidate supplies study mechanisms and software controls. It has not
exported ordinary Notes/Calculator trajectories, attached a live Root/Session
owner, registered an independent evaluator, or measured a held-out business
benefit. A future native export must be bounded, immutable and owner-local,
preserve original identities and UNKNOWN, and retain observation/receipt bytes
before any adaptation. Its exact native source, recovery and deployment require
their own qualification. No Python study record establishes those properties.
