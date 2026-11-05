# Historical input provenance

This additive record resolves names retained by the original source reviews.
Those reviews keep their original bytes and source/time scope. Current source
identities and actual native observations are recorded in
[native-validation.md](native-validation.md) and [validation.json](validation.json).
The [machine-readable mapping](history/provenance-map.json) records the exact
hashes and the limited path relocation described below.

## Original source handoff and caller inventory

The original [composition review](source-combination-review.md) names three
historical inputs:

| Original name | Archived location | Identity and scope |
| --- | --- | --- |
| `SOURCE_ACCEPTANCE.md` | [Original source handoff](history/SOURCE_ACCEPTANCE.md) | Exact SHA-256 `136d466db2f89cccad2787f19c0e7e68e8456836c090c186ad29360fe7b6fc99`; the original a20-based source handoff, before native formatting and the later current-trust regression |
| `final-caller-inventory-review.json` | [Original caller review](history/final-caller-inventory-review.json) | Exact SHA-256 `484bf9440c4ceab992f0d6f486f62507f2d93fb07227ac0ef0ec82a7eeadcbfe` |
| `final-rust-callers-derived.txt` | [Archived derived inventory](caller-inventory-final-derived.txt) | Exact SHA-256 `ce42f0e52110ef024e3304cc7400222c2db0dd070b9cc2a1098a861ab93804da`; the original scan bytes under the archive's descriptive filename |

The separately archived [caller-inventory-review.json](caller-inventory-review.json)
is a path-relocated copy, SHA-256
`ae5b9baa42a0a78f1eac44ebe15f37c3828efe95849b32e28287c70d80822574`.
Its only byte change replaces `derived_final_inventory.path` from
`product/stack-review/final-rust-callers-derived.txt` with
`caller-inventory-final-derived.txt`. Its verdict, source identities, counts
and evidence digests remain unchanged. Both original and relocated identities
are retained explicitly; they are not represented as byte-identical files.

## Earlier plan review and available inputs

The [early plan review](native-plan-independent-review.json) refers to plan
SHA-256 `e8c15141bd9bf28956551abf15e1f5020d7f4697f8a690f9840d248873ea8d57`
and plan-document SHA-256
`ed6be9dcd849115b4f1510f5511cc91977103bfcef24bf5f8145e4a44310f21a`.
Neither exact input revision is included in this evidence package. A
[read-only search of the available task files and native transport archives](history/initial-plan-exact-search.json)
found no matching original. No input was reconstructed, normalized or relabeled
to stand in for those missing bytes. This search does not establish absence
from other storage or history.

That review remains a historical semantic and source-adaptation review of an
earlier preparation. It does not prove the identity or execution of either
later frozen bundle. The current gate instead has its own
[independent review](post-fix-native-gate-review.json), which binds:

| Actual gate input | SHA-256 |
| --- | --- |
| [Executed plan](native-round2-gate-v2/plan.json) | `00b4d289a635ae36865dc70732a1a10a03a8fb81575be5b5eba0b21fce7027fe` |
| [Executed runner](native-round2-gate-v2/run_native_round2.py) | `46552f047784d07b825cec59e0358cfbb02a010f448b7538bb0fadc15ea2f7df` |
| [Independent gate review](post-fix-native-gate-review.json) | `cf8c1b758245f57b22800fdcc54832ec84fd86a3b83f866e88fbbb0aff26ab08` |

## Frozen preparation state and current execution state

Both `native-round2/` and `native-round2-gate-v2/` are frozen preparation inputs.
Their original `NOT_RUN`, `runner_executed=false` and 06ad manifest identities
retain their preparation-time meaning. The final-positive manifest pins 14
source-file identities; the explicit execution head and its whole-tree identity
are verified separately. Later raw receipts record execution on the stated
positive source plus each isolated mutation, followed by exact restoration.

Keep those frozen input bytes unchanged. Current phase outcomes, later source
identities and verification limits belong in the top-level validation records
and original native receipts. Historical source review and a prepared plan do
not themselves establish native success, original platform qualification,
product recovery, adaptive benefit or release approval.
