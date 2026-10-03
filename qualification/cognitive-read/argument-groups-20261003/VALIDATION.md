# Private cognitive argument groups and strict owner lint

Exact f0b175af Agentd Linux job111162745710 (run37108886695) passed its
16 daemon tests, with four existing skips, then reported13 strict Agentd
library diagnostics. This change addresses only four owned cognitive findings:
two long parameter lists, an error-observation closure, and alert divisibility.

Borrowed `ContextReadRequest` and `ContextRevalidationInput` group the existing
read request fields and claimed final-use snapshot fields. All17 caller argument
vectors were checked against their original fields, including mutated-digest,
oversized-item and changed-retrieval-context tests. Test wrappers forward the
same borrowed group. No public protocol field, serialization, digest, SQL,
resource limit, authorization, clone or cached owner cut is added or changed.
The complete read and final-use bodies retain their validations and await order;
the only body transformation is `inspect_err` observing the same error while
incrementing the same stale-cut counter. The alert threshold remains nonzero
and the divisibility predicate is equivalent. Existing context, HNMF,
publication-fence, final-use, metrics and real product tests remain required.

Local validation: the17 caller mappings and owner-body preservation checks pass;
105 cognitive Python tests pass with three existing skips, then26 workflow and
candidate checks pass. Scoped formatting and whitespace checks pass. These are
source/wiring checks, not fresh owner Rust execution. The existing cognitive
source/merge and Agentd process workflows supply that execution after publication;
no broad local workspace build or shared-cache restore was performed.

TaskFlow owns the outer automation recovery enum repair separately. Remaining
browser, plasticity and intelligence-product findings are not suppressed or
claimed resolved by this change. Paused AuthBus/state/workspace-lock paths remain
unchanged. The distinct runtime PR1329 retained run coordinator still rejects an
advanced spawn-generation composition without authenticated handoff evidence;
the cognitive branch's in-memory coordinator is not substituted into that owner.

## Exact preceding candidate

For source f0b175af5b26d92b6134db69a486344ae6657860 and deterministic merge
d6977de5766f00d39de9062d4bd4285ccd61e212, tree
ad64a92f1b6683d1e628bf83783d6fcf3974e4ac, both cognitive qualification bundles
verify194 checksum and193 receipt entries. Source artifact11269642020 has ZIP
`92c6b602002e452c795e4385a904f3465282142b7bf01aa83fad53c8bc60f28a`; merge
artifact11269712358 has ZIP
`06f9a50ecd8500508cbf0d09b0aef0dd824d3c8b5fe5928272770856934af51e`.
Both pass287 owner,226 Agentd and56 cognitive core tests, actual read/replay,
write-smoke, native final-use, locked fuzz and clean-source gates. Only strict
and compatibility Clippy fail in those receipts, each at five paused AuthBus
findings. The separate Agentd --no-deps lane reaches the13 owner findings above.
Darwin passes399 library tests, including all five repaired fixture cases, with
19 release-install failures remaining. No result establishes production,
independent, activation or release acceptance, or execution of this new refactor.

Published source `8876dbf4cc9292c71281c7e99b96e149e68b181b`, tree `39c3c247f1f7aa4e4eb9a36581a3789bfd79b21e`, is the new cognitive.read observation. All227 previous paths remain; the explicitly changed metrics dependency adds the228th object. Historical sourceBase and every claim flag/other map field are identical; unrelated module maps are unchanged. The prior map blob `f7e23a1f1e10ca7a6d4f3c90e0e9bc3120f33ef2` remains in history.
