# kernel.evidence independent acceptance handoff

Independent acceptance is an externally governed action. The evidence store
verifies and persists the resulting signed record; it does not create the
independent identity that makes the record independent.

## Ceremony owner

The repository already contains the qualification-only
`codex-hepta-operator-acceptance` ceremony. It authenticates an allowed signer,
challenge/nonce, trust policy and signed acceptance material. It is intentionally
excluded from product callers and grants no promotion authority.

For `kernel.evidence`, the ceremony output is admitted only after an adapter
binds it to a `QualificationEvidenceEnvelopeV1` with claim class
`independent_decision` / protocol `IndependentDecisionReceiptV1`.

## Mandatory binding

The admitted record binds:

- exact candidate ID, commit and tree;
- exact source-head and deterministic synthetic-merge execution evidence set;
- signer principal and controlling authority;
- Ed25519 signing identity and credential/trust-chain digest;
- reviewer/operator role;
- evidence-set digest;
- decision and bounded conditions;
- observation and expiry;
- predecessor, supersession or revocation lineage when applicable.

The derived `IndependentDecisionReceiptV1` contains exactly the canonical
registry fields: decision ID, candidate ID, role, principal ID, signing-identity
digest, evidence-set digest, decision, conditions and expiry.

## Independence rule

The independent decision cannot share the generator/evaluator's principal,
controlling authority, signing key or delegated credential chain. Different
display names, service labels or aliases are not independent identities.
`verify_chain` fails closed when selected required roles collapse onto the same
principal, controller or signing identity.

## Execution procedure

1. Freeze the exact candidate commit/tree and evidence-set digest.
2. Retain successful source-head and deterministic synthetic-merge receipts.
3. Run the external operator/reviewer ceremony under the independently
   administered trust root.
4. Verify the ceremony signature and current revocation state.
5. Adapt the authenticated signer to `AuthenticatedEvidenceIssuerV1`.
6. Sign the canonical qualification envelope with the independent signing key.
7. Append it through `HeptaEvidenceStore::qualification().append_receipt`.
8. Reopen the store read-only and run `verify_chain` for the required roles.
9. Retain the resulting receipt and external ceremony record outside the database.

Until steps 1-9 actually run under an independent identity, the canonical
`independentAcceptance` claim remains false. Repository authors and CI cannot
self-grant it.
