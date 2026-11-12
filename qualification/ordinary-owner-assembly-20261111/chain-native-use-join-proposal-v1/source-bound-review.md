# Chain HEPLCP04 native-use join — isolated proposal

## Status and custody

This is an uninstalled source proposal stored only as loose immutable Git
objects in TrillionniumFoundation/hepta-private-ci. No Chain blob, tree,
commit, ref, pull request, workflow or native process was created or changed.

The final read of Chain #909 still showed open Draft, head
e338c000f26e9357ed33213624da787a3a009ed9, tree
876aa62d1ab49458d29e9168f4c69e7b47b8884b, base
c84162378f34b9284e90587df4c466dfee3e193b, merged=false. The prior final-CI
evidence commit remains 6a8c1bdcd8d698fdf30fa3ed8b2a3ab3a2611f25; this proposal
does not rerun CI or turn structural qualification into a green whole repository.

Root reported the original unchanged preflight passed. That does not establish
the AGENTS-required ProfHepta through HeptaRuntime local GitHub write channel:
the actual gh lookup was unavailable. This proposal does not substitute the
GitHub connector for that channel. All CREATE operations here target Hepta
evidence, not Chain.

## Concrete source change

Three paths, eleven unique replacements:

| Path | Original blob | Proposed blob |
| --- | --- | --- |
| scripts/cell_learning_local_decision_join.py | 1409d50d835e12c32341a3e650f53191915b8030 | dabf403b0988de6a6dad9ad198ac22cad1542fa8 |
| scripts/test_cell_learning_local_decision_join.py | 02515dcb1b33afae4b350a7272db662402819064 | a8c35861954c6b68dd2af5453fa1365020380217 |
| docs/development/specs/pon/HEPLCP04_LOCAL_DECISION_INTEROP_V1.md | 231a2200510edb81efed565a4563f768105de677 | 0e21285b51a45a865fcb44b2b0089c9ebbcc5543 |

The original structural review function is preserved byte for byte. The
existing four-file CLI mode retains its schema and result semantics. The new
explicit mode requires both readback and expected files and both byte pins.
A partial optional group is an error. The real main function calls the new
review_native_local_decision_use entry; this is not an orphan helper.

That entry composes the unchanged original structural and native-use readers.
It requires an actual nonpending native use and joins the Selection head and
decision predecessor, original source identity and receipt, complete original
parent bundle, target principal/agent/Cell, selected complete descriptor,
Selection digest, and the sole completed NextUse/RetainedModelNextUse observation.

The retained/adopted choice comes from tag 9 and the actual selected descriptor.
DeferCandidate and RetainParent preserve qualified Evaluation, UpdateCandidates
Proposal, no_update=false and the complete original parent. They are never
relabelled as Evaluation/Proposal NoUpdate.

The new report has a distinct namespace:
trnm-cell-learning-local-decision-native-use-readback-v1.
ACK consistency is reported only after all original native and cross-record
checks. The copied original report retains DENY_ALL, NOT_EXPORTED, HOLD_NO_GO,
all original authentication refusals, independent_consumer_verified=false,
hepta_final_use_accepted=false and production_activation=false.

## Source-bound native export interface

The source review was limited to the actual original export path at Hepta
cbf6ca7dd619589be3e9e98755f185d34d0f7413:

| Source under codex-rs/hepta-agentd/src | Blob | Actual contract |
| --- | --- | --- |
| neuron_generation_learning_runtime.rs | de50528a4245324360b465cc93bc25519255f2ea | Bounded actor read_learning_next_use_readback and read_learning_updated_next_use_readback. |
| neuron_generation_learning_readback.rs | 3a8d21d2c5d10154f746ae781dacffaa6de23a36 | Reads the original journal/publication/intent, derives observation and payload, binds Selection snapshot and its predecessor, final require_current. |
| neuron_generation_update_learning.rs | 88c5ec9658ef561af3658f5a73f8bfa7f89d9243 | Retained path checks the actual next-task complete parent, exact owner progression, current journal and OwnerDrainedSameModel. |
| neuron_generation_update_adopted_learning.rs | 6ed28321bbc1b51b442445b70ff4794b88d1af50 | Adopted path checks the actual selected qualified candidate, original reset publication and both manifest contracts. |

The export occurs while the original coordinator awaits NextUse. Its learning
head is the Selection cut; its decision head is that receipt's predecessor.
The original observer then appends precisely one completion receipt. This
ordering matches the proposed reader. A completed coordinator cannot simply
be substituted into the original export API.

The API exists; this report does not establish an ordinary deployed caller,
a newly captured v4/native-use pair, or independently trusted expected pins.

## Controls and actual verification

All fourteen existing test method bodies remain exact. Seven added methods
cover wrong native byte pin, pending native ACK, old-iteration/v4 head mismatch,
incompatible disposition, attempted authority escalation, incomplete CLI
argument group, and actual CLI expectation/head refusal.

The native files are the unchanged original historical engineering exports
already retained in Chain. Their fixture expectations are not deployment
authority. The existing v4 corpus has explicitly synthetic policy/Selection/
NextUse observations emitted through the original codec/coordinator. The new
tests do not manufacture a positive v4/native-use pair, mock a successful
reader, sign a grant, or add a business completion count.

Performed: CREATE/GET exact byte checks in Hepta; full Git/length/SHA256 checks;
eleven forward and reverse unique replacements; fourteen old test bodies
preserved; original structural review exact; static inspection of original
producer and reader contracts; direct comparison of original unequal fixture
Selection/export heads.

Not performed: Python execution, AST compilation, original checker, formatter,
Cargo/native execution, tests, CI, installation or Chain publication. The seven
new controls and all proposed runtime behavior remain unexecuted.

## Remaining code and deployment boundaries

| Boundary | What this proposal supplies | What remains absent or unaccepted |
| --- | --- | --- |
| Offline Chain consumer | A concrete CLI path to original native-use validation and exact tag-9 join. | An ordinary application/runtime caller that obtains and consumes these actual records. |
| Trusted input custody | Strict byte pins and unchanged validators. | Independently retained freeze, Root profile and native expectations from the actual owner; public JSON is not that owner. |
| Original A/B/local policy | Preservation of exact commitments and complete descriptors. | Ordinary execution, real training/evaluation, signed local policy/Selection/NextUse and real holdout/cost evidence. |
| Independent C | Exact same-principal/agent/Cell, distinct-run matching. | Independent consumer identity/control and adoption evidence; no cross-owner authorization is invented. |
| FinalUse/currentness | Original export refuses authority transfer; reader retains NOT_EXPORTED. | Actual current live owner, revoke/withdrawal and FinalUse validation at the consumer; a historical ACK cannot supply them. |
| Process lifecycle | No runtime or shutdown code changed. | Real daemon plus Root OS restart/physical join qualification. |

The original acceptance counts remain ordinary_complete_chain /
positive_adoption_chain / no_update_or_rollback_chain = 0 / 0 / 0.
This proposal changes neither source activation nor acceptance criteria.
