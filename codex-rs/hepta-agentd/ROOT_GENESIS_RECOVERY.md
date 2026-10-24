# Original Root installation before the first checkpoint

An installation can retain a complete signing identity and physical database
while no original writer has yet published its first checkpoint. This state
does not have a predecessor Current, checkpoint token, or local generation
zero. Recovery must not manufacture any of those values.

`RetainedCheckpointGenesis` retains one bounded immutable observation in the
original Root checkpoint directory. It records the actual initial Root
lifetime, complete initial `CognitiveRecoveryAnchor`, original issuer ID and
public key, and the originally configured policies. The record is saved only
while the original checkpoint publication lock proves both its canonical and
temporary names absent and the original issuer request lock proves sequence
zero, no writer authorization, and the untouched original revocation head.
The complete private physical material must verify before and after saving.
No key material is serialized.

The record uses the original Root observation storage and its existing
file/rename/directory durability and exact readback. Its logical ID is
`checkpoint-genesis-v1.<AgentId>`; the physical name uses the original
`observation-v1-<SHA256(id)>.json` mapping. It is an installation input, not an
authority frontier or an operation ledger. Opening it neither asserts that
the issuer is still unused nor permits publishing a new Current.

The unused native policy administration path checks the actual Root PID and
kernel initial pair from the original launcher. It retains the same issuer
request lock across checking the full unused state and comparing and setting
only its two finite CPU namespace policies. The old private key, sequence,
revocation head, and all original lease times remain intact. An already used
issuer, a checkpoint or partial first-checkpoint candidate, a different
physical material, or a different public key is a refusal. The original
successful-checkpoint boot retirement and namespace APIs remain separate.

The new Root tests exercise actual original issuers, real physical SQLite
material, protected files, retained key identity, and original publication
absence. They do not impersonate kernel roles or claim a native second boot.
Rust compilation, Root tests, and original native entry acceptance are tracked
separately. The Native installation composition and first signed-proof
continuation must also be wired and tested before this module closes the
installation recovery blocker.
