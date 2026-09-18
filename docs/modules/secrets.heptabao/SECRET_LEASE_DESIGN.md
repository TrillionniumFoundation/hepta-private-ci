# SecretLease lifecycle design

## Identities

Every operation binds subject, consumer, provider origin/CA, namespace,
resource identity and a caller-owned operation ID. The provider lease ID remains
inside `SecretLeaseHandle`; public metadata uses its digest.

## Issuance

`request_secret_lease` claims final-use authority, durably fences the operation,
then performs one provider-native dynamic credential read. On a valid response,
the opaque lease handle is durably registered before secret callback entry.

Outcomes distinguish delivered, delivery blocked by a later authority check,
registry blocked after a known provider effect, rejected, and indeterminate.

If the issuance request may have reached the provider but the response/lease ID
is lost, the operation remains indeterminate. Generic OpenBao lease lookup
cannot recover a lease whose ID was never observed. Automatic retry therefore
requires a provider-specific stable operation-key plus status-lookup contract.

## Renew and revoke

Known lease operations use the opaque handle and a new operation identity.
Renew and revoke are admitted once and are not automatically retried after an
ambiguous network/provider outcome.

A known lease can be reconciled with `lookup_secret_lease`, which observes
provider state without replaying the mutation. Lookup does not prove that a
specific lost renew was applied; it establishes current provider state.

## Final delivery boundary

Dynamic issuance performs a second live final-use check immediately before the
trusted callback. If revocation wins after provider issuance but before callback
entry, `DeliveryBlocked` retains the opaque handle so the host can revoke or
reconcile the credential rather than orphaning it.

The callback is trusted privileged code. Preventing ordinary return of secret
bytes does not prevent an authorized malicious callback from exfiltrating them.
