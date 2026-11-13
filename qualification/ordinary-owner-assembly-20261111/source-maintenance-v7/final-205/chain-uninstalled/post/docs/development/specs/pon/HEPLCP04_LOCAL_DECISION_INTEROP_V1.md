# HEPLCP04 local-decision structural readback

This explicit, read-only profile consumes the original HEPLCP04 codec from
Hepta source afd2c91b3b9ef75ab9a174e3af772ad322118f7a (#5948), building
on Chain source 297bb40798ca1b4e4a987ef00582067282cda4e9 (#907).
The existing HEPLCP02 readers retain their exact source and refusal behavior.

The [reader](../../../../scripts/cell_learning_local_decision_join.py)
requires externally supplied byte pins for a Selection cut, completed cut,
initial freeze and schema-2 Root profile. It replays the original first five
stages through the existing parser, then requires precisely:

1. Qualified Evaluation and UpdateCandidates Proposal.
2. One original-selector LocalDecisionV2, tag 9, bound to the exact proposal
   head, trained candidate, chosen version, nonzero policy and reason.
3. A separate Selection receipt for that chosen version.
4. NextUse for adoption, or RetainedModelNextUse for defer/retain, under the
   same original actor and a different run, with the exact Selection digest.

The local receipt digest uses the original distinct
hepta.learning.iteration-local-decision.v2 NUL-terminated domain. The codec's
tag/disposition bytes and five ordered digests are reproduced exactly.
Eight receipts are the maximum; the original 8,192-byte checkpoint limit remains.
Header relabels, truncation, trailing bytes, unknown choices, duplicate decisions,
out-of-order stages, expired observations, wrong owners, mismatched scope and
self-consistent rehashing of the wrong selection are refused.

The Root profile remains separately pinned and must bind the original
HEPLCP02 initial snapshot, Cell/Organ update scope and update rule. A later
choice does not excuse a trained candidate from the original component mask.
A local defer or retain leaves no_update=false, evaluation_disposition=qualified
and proposal_disposition=update_candidates; it reports the local choice
separately and selects the complete original parent descriptor.

## Exact verification boundary

A checkpoint holds receipt commitments, not the original signed attestations.
Recomputing its signing domain and digest does not verify a signature or
authenticate an owner, policy, source execution, independent custody or freshness.
The caller-supplied pins do not establish these properties either.

The default four-input profile does not consume a native-use export. It retains
its original schema and acknowledged_use_observed=false. The separate explicit
native-use profile below can report a structurally matching acknowledged use;
neither profile grants use authorization.

A same-actor different-run observation does not establish independent C.
All training, cost, installation, settlement, independent-consumer and FinalUse
qualification fields remain false; authority is DENY_ALL and status HOLD_NO_GO.

## Explicit native-use join

Supplying both --readback and --expected, each with its -sha256 pin, selects
trnm-cell-learning-local-decision-native-use-readback-v1. Every one of these
four optional arguments must be present together. A partial group is refused;
omitting all four preserves the original structural profile.

The CLI calls review_native_local_decision_use. That function first calls the
unchanged review_native_local_decision and then the unchanged original
cell_adoption_readback.review_native_learning_use. The second reader validates
the exact native export envelope, payload commitment, complete manifest,
original publication and public grant bindings, intent, committed step,
journal observation and expected inputs. This proposal does not alter that
reader or the existing HEPLCP02 completion/scope readers.

The additional join requires all of the following:

1. No native pending work or pending delivery. Model STOP and a terminal
   episode remain separately reported; an ACK is not either fact.
2. Native retained/adopted disposition agrees with the actual tag-9 choice.
   DeferCandidate and RetainParent use the complete parent descriptor while
   no_update remains false; AdoptCandidate uses the trained candidate.
3. The native learning head equals the exact Selection-cut head. Its decision
   head equals that Selection receipt's predecessor, including LocalDecisionV2.
4. Original learning operation, source run, completed task receipt, selected
   artifact and complete parent bundle match the frozen request.
5. The publication target has the same original principal, agent and Cell.
   Its new run and every final use field must match the completed observation.
6. The Selection digest and selected bundle match the native observation,
   native manifest and complete selected version descriptor.
7. The sole appended NextUse or RetainedModelNextUse observation equals the
   original native checkpoint, committed step and cutover/publication values.

Only then does the new report set acknowledged_use_observed=true. That flag
describes the consistency of the supplied original bytes. It does not
authenticate their custody, signatures, freshness or external producer.
All authority and business-qualification refusals from the structural report
remain intact, including independent_consumer_verified=false,
hepta_final_use_accepted=false and production_activation=false.

### Actual native producer contract

The relevant original Hepta source was read at
cbf6ca7dd619589be3e9e98755f185d34d0f7413. The paths below are under
codex-rs/hepta-agentd/src:

| Source | Git blob | Exact responsibility |
| --- | --- | --- |
| neuron_generation_learning_runtime.rs | de50528a4245324360b465cc93bc25519255f2ea | The existing bounded actor exposes read_learning_next_use_readback and read_learning_updated_next_use_readback. |
| neuron_generation_learning_readback.rs | 3a8d21d2c5d10154f746ae781dacffaa6de23a36 | export_next_use derives use from the actual held journal/publication, captures the Selection head/predecessor, and retains DENY_ALL/NOT_EXPORTED. |
| neuron_generation_update_learning.rs | 88c5ec9658ef561af3658f5a73f8bfa7f89d9243 | The retained path requires the actual next-task bundle to equal the complete original parent, exact original owner progression and OwnerDrainedSameModel. |
| neuron_generation_update_adopted_learning.rs | 6ed28321bbc1b51b442445b70ff4794b88d1af50 | The adopted path requires the qualified selected candidate, actual model-reset publication and both complete manifest contracts. |

Those are real export APIs, not a new authority issuer or evidence that an
ordinary deployment has invoked them. The local CLI is an explicit read-only
consumer. This change does not install an ordinary runtime caller, obtain
signed tag-9/Selection/NextUse attestations, issue a grant, or prove an
independent consumer adopted a published artifact.

The existing HEPLCP04 corpus contains synthetic policy/Selection/NextUse
observations emitted through the original codec/coordinator. The existing
native-use corpus is a separate historical engineering run. They cannot be
joined into a positive record by relabeling or rehashing. Seven added controls
use unchanged historical exports as refusal inputs: wrong pins, pending ACK,
cross-iteration heads, incompatible disposition, attempted authority
escalation, partial CLI arguments and exact CLI expectation/join refusal.
No successful HEPLCP04/native-use pair is manufactured by the tests.

A later qualification run must capture the actual v4 Selection cut, the original
native export while that coordinator awaits NextUse, and the single completed
continuation, together with independently supplied original freeze, Root scope
and native expectations. This proposal supplies no such new execution record.
The ordinary_complete_chain / positive_adoption_chain /
no_update_or_rollback_chain acceptance counts remain 0 / 0 / 0. Independent C
and actual daemon plus Root OS restart remain unaccepted.

## Reproduction

The retained isolated exporter calls the unchanged pinned Rust codec and
coordinator. It replays a historical original HEPLCP02 input prefix, then emits
three explicitly synthetic policy/Selection/NextUse cases. Its 15 cuts and
24 signing payloads exercise format interoperability only. No optimizer,
evaluator, daemon, actual next task or production FinalUse executes.

Run the [controls](../../../../scripts/test_cell_learning_local_decision_join.py)
with **python3 -B scripts/test_cell_learning_local_decision_join.py -v**.
The default CLI requires four complete file/pin pairs:
--selection-checkpoint, --completed-checkpoint, --root-profile, --freeze,
each with its corresponding -sha256. The explicit native-use mode adds both
--readback/--readback-sha256 and --expected/--expected-sha256. Both modes print
one read-only report and do not write a file, invoke a model, sign, adopt,
dispatch or pay.

Original v4 attestations, ordinary stage-owner assembly, independent B/C,
published CURRENT/withdrawal and whole daemon/Root cold recovery remain open.

The [native reproduction entry](../../../../evidence/heplcp04-interop-20261111/reproduce_native.py) verifies every original source blob,
assembly asset and retained input before invoking the pinned offline Cargo graph.
Provide a clean checkout of the exact Hepta commit and two fresh external directories:

```bash
python3 evidence/heplcp04-interop-20261111/reproduce_native.py \
  --hepta-source /path/to/clean-afd2-checkout \
  --chain-source /path/to/this-checkout \
  --workspace /path/to/new-native-workspace \
  --output /path/to/new-native-output
```

Cached Cargo dependencies are required. The assembly shim exercises the original
codec and coordinator; it does not assemble or qualify a complete Hepta daemon.
