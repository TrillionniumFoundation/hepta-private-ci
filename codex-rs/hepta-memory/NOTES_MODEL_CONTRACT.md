# Notes identity and version domains

The canonical interchange example is
[`tests/fixtures/notes-model-v1.json`](tests/fixtures/notes-model-v1.json), with
SHA-256 `3d011551020a77df728d3c79c5b04639c3f79e2fb2db1bc8f38a3c1a60a1c88f`.
The same bytes are consumed by Desktop core, this original memory owner and
Agentd's typed bootstrap test. It is data, never an authority fixture.

| Domain | Current contract | Compatibility |
| --- | --- | --- |
| Target/operation | Session instance, task ID, incarnation; `trill.notes.replace.v1`, wire schema 1 | Exact immutable target, operation, predecessor and receipt binding |
| Application checkpoint | `format = trill.notes.checkpoint`, schema 2 | Unmarked schema 1 is read-only legacy input; opening/observing never rewrites it |
| Session bootstrap | Schema 2, exact target and two original descriptors | A checkpoint version is not a bootstrap version |
| Initial startup reservation | Schema 1, exact target and fresh reservation nonce | Activation releases the existing two-descriptor bootstrap |

The next legitimate state-changing application commit writes checkpoint v2.
This changes its envelope, not target identity, revision, pending receipt,
retired receipt, operation ID or predecessor. Unknown, mixed, missing and
duplicate format/version fields are rejected. A text-only open-copy has a fresh
target and revision domain with no old pending/retired receipt. It is not a
migration of the original identity.

Hepta does not parse application checkpoint files or rewrite application state.
Its original `NotesTargetIdentity`, intent validator and full terminal-receipt
parser remain authoritative for the existing operation wire. Recovery reads the
actual application through the same exact old target, helper and original owner.
The same-source Desktop recovery helper handles both application checkpoint
inputs. The ignored actual-App current/legacy owner tests require those built
companions and retain the original one-effect, exact receipt, lost ACK and
original-owner reopen oracles; SQL handle closure is not a Root process crash or
power-loss proof.

See [Notes retirement](NOTES_RECEIPT_RETIREMENT.md) for source persistence and
metadata ACK ownership, and [original-thread tools](../hepta-agentd/NOTES_ORIGINAL_THREAD.md)
for the model-call bridge and the product evidence it still requires.
