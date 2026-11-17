# Closed Run02 research evidence and final interpretation

Read [the final Chinese results and decisions](summary/RESULTS_AND_DECISIONS.md)
together with the original [result review](result-review/), [diagnostic-interface
review](interface-review/) and [posthoc material](posthoc/). Their individual
source SHA values and storage locations are in FINAL_DOCUMENT_BINDINGS.jsonl.

## Exact original export

The original Run02 ZIP contains 1,687 members. Its 29,880,237 bytes have SHA256
a852fa6d9ce8317edd15bd7e6edeb3ee12e97e3d27c4ba179e5fe2c34846ad61.
All 97 original Git export objects remain exactly recoverable. The 93 original
archive parts, original TRANSFER_MANIFEST.json and RESTORE.txt retain their
original bytes in export/. The two original JSONL index parts retain their
original names and bytes inside the lossless export-index-original-parts bundle.
ORIGINAL_97_OBJECT_RESTORE_MAP.jsonl maps every original object.

The index .bin names do not make JSONL binary to Git. A lossless ZIP preserves
their exact bytes while meeting the text-stage limit; no diff attributes or
publisher limits were changed. No original diagnostic, result, failed receipt
or reported unknown value has been rewritten by publication.

To restore, first verify and concatenate the ordered parts described by
prepared-v2/export-index-original-parts/MANIFEST.json into a NEW ZIP. Verify its
CRC and the two member identities in MEMBERS.jsonl. Extract to a NEW directory;
the members have research-final-export-02/ paths. Place those two index parts
alongside the 95 directly retained export objects in a new export directory,
using the 97-object map. Follow the unchanged original TRANSFER_MANIFEST and
RESTORE: verify every part, reconstructed ZIP/index, CRC, member path/size/SHA,
then extract to a new target. Reject traversal, symlinks and existing targets.

The research-sft-02/RESULT.json and research-diagnostic-02/DIAGNOSTIC.json are
members inside the original ZIP, not directly published standalone JSONs.
Their original interpretations and any later offline analysis are distinct.

## Controllers, snapshots and posthoc boundaries

The closed controller, observation, operation and prior-publication bundles
preserve original bytes. Their parts, archive hash and member index are in each
prepared-v2 bundle manifest. Reconstruct the archive at a new destination before
extraction; its whole transport ZIP is not separately duplicated in Git.

Watch and intermediate observations are non-atomic snapshots. Earlier lost or
incomplete controller captures remain visible beside later original readbacks.
They are not additional independent samples or substitutes for final owned
receipts. Source presence is not proof every program executed: the first
reconciled preparer is explicitly unexecuted; v2 has its own execution evidence.

The original frozen diagnostic remains unchanged. The interface review and
posthoc analysis retain their stated timing, assumptions and limits.
Posthoc analysis is not a retroactive pre-registration, a new training run,
a new independent task, or a reason to erase the original diagnostic output.

## Source and publication provenance

The selected operations source inventory is checked against exact base Git
blobs or newly published source. All three earlier publication builders and
every current package program are readable, including failed historical versions.
Packaging failures, partial outputs and successful observations are preserved.
The builder includes its stable source bytes, never its own future results.

The earlier Run01 resource failure remains in the previously published
research-run01-and-run02-preparation/run01/export/ archive. Run02 does not
replace it or erase its cost. Source, cost and global-total uncertainty must be
read with the final review, not inferred from exit codes or archive success.

This archive has an explicit cutoff before root validates or publishes this
operation06 input. Its prepared validation source is included; future validation,
native publication and Draft PR receipts are outside the input they describe.
No recursive trailing package is implied.

This publication performs no model, training, test, business verifier or C call.
It adds no independent samples and does not establish scientific confirmation,
Circuit, PoUW eligibility or production adoption. All 64 core Git blobs remain
unchanged. Root alone performs native Git publication and Draft PR operations.
