# Remaining Windows deletion boundary

The actual Windows probe proves a separate deletion-policy failure after normal
outside writes have already been blocked. A successful parent DELETE_CHILD check
can authorize deletion of a child whose direct permissions are insufficient. The
Microsoft filesystem security documentation describes this alternate path for
delete and for rename/hard-link replacement. The probe also refused DELETE on one
partial root, so the evidence does not support a blanket claim that every DELETE
check ignores restriction.

The normalization repair addresses representation and idempotence only. The
capability allow mask already excludes DELETE_CHILD; deleting that bit again or
adding another capability deny to a protected child cannot establish the missing
parent restriction. Removing WRITE_RESTRICTED would change read semantics, while
adding broad identity SIDs can grant access through their existing ACL entries.
Neither is accepted as a repair of the existing contract.

Two concrete routes remain. A precise admission refusal can contain the unsupported
legacy guarantee before policy preparation changes the filesystem. Such refusal
must retain the original full-read/inside-write/outside-no-delete tests as open
functional gates. Alternatively, an enforcing backend must control actual native
file operations. A kernel filesystem boundary needs stable process and target
identity, all deletion/rename/link variants, alias handling, and inherited handles.
A guest with read-only host mappings is a documented isolation building block, but
its namespace, writable mapping and protected-subpath behavior require a new
contract and real tests. AppContainer alone also changes resource-read admission.

No enforcing replacement or additional native permission experiment is claimed
here. RESULT.json distinguishes observed facts, implementation inferences, rejected
shortcuts, concrete validation work and primary Microsoft references. The current
legacy deletion guarantee remains an explicit blocker.
