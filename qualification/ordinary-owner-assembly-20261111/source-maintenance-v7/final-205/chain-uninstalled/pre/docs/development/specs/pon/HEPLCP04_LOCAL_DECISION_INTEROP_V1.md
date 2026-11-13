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

This profile does not consume the original native-use export. It therefore
reports acknowledged_use_observed=false and grants no use authorization.
A same-actor different-run observation does not establish independent C.
All training, cost, installation, settlement, independent-consumer and FinalUse
qualification fields remain false; authority is DENY_ALL and status HOLD_NO_GO.

## Reproduction

The retained isolated exporter calls the unchanged pinned Rust codec and
coordinator. It replays a historical original HEPLCP02 input prefix, then emits
three explicitly synthetic policy/Selection/NextUse cases. Its 15 cuts and
24 signing payloads exercise format interoperability only. No optimizer,
evaluator, daemon, actual next task or production FinalUse executes.

Run the [controls](../../../../scripts/test_cell_learning_local_decision_join.py)
with **python3 -B scripts/test_cell_learning_local_decision_join.py -v**.
The new CLI requires four complete file/pin pairs:
--selection-checkpoint, --completed-checkpoint, --root-profile, --freeze,
each with its corresponding -sha256. It prints one structural report and
does not write a file, invoke a model, sign, adopt, dispatch or pay.

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
