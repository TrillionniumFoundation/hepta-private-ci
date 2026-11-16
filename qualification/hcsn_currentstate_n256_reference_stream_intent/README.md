# N256 independent-reference stream interface (HOLD)

This package freezes only the canonical third-stream row and provenance
interface required by Draft #6312's separate candidate and oracle error gates.
It does not implement or execute a reference provider.

The interface binds the authentic N256 input, roster, candidate, oracle and
comparator source identities; canonical coordinate ordering; exact warm,
coarse and cold capsule scheduling; reduced rational time/support fields; and
canonical finite FP64 hexadecimal values. Future provenance must identify a
precommitted provider source distinct from candidate, oracle and comparator,
an independent review, a runtime profile and a provider admission. Reuse of a
candidate/oracle implementation or numeric kernel rejects.

The checked-in request leaves the provider source, provider admission and
numerical idempotency key null. The execution gate therefore rejects before a
provider or stream can be opened. Tests use only three synthetic stdlib rows;
they do not run N256 dynamics or grant large-grid qualification.

Historical #6295 RED, #6302 RED/UNKNOWN and #6303 joint-admission RED remain
unchanged. Full N256 numerical work, saved-state byte pairs, C2 full replay,
HPCA external custody, production adoption and global closure remain open.
