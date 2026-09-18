# kernel.evidence production composition handoff

## Current product surface

`codex-hepta-evidence` is already a registered durable product-evidence crate.
The current named product writer host is
`codex-rs/ext/hepta-governance/src/install.rs`; the App Server also has a
read-only S5 evidence-summary consumer. Those callsites prove the crate is not a
caller-zero library, but they do not by themselves compose the new qualification
semantics.

The qualification target API is exposed by the same authoritative store through:

- `HeptaEvidenceStore::qualification().append_receipt(...)`;
- `HeptaEvidenceStore::qualification().verify_chain(...)`;
- `HeptaEvidenceStore::qualification().query_claim(...)`.

The existing governance `HeptaEvidenceStore::append_receipt(&GovernanceReceipt)`
surface remains unchanged.

## Required production writer binding

A production qualification writer is established only when a named product host:

1. opens the canonical `HeptaEvidenceStore` from its product state root;
2. authenticates the producer outside the receipt payload and constructs
   `AuthenticatedEvidenceIssuerV1` from that authenticated identity;
3. binds principal, controlling authority, verifying key and credential-chain
   digest to the current authorization/revocation generation;
4. validates the exact candidate commit/tree and registered claim protocol;
5. calls the qualification `append_receipt` façade;
6. treats an append acknowledgement only as durable evidence storage, never as
   selection, promotion, deployment or external-effect success;
7. exposes reads through `query_claim` / `verify_chain` without granting write
   authority to read-only consumers.

Constructing `AuthenticatedEvidenceIssuerV1` from fields supplied by an
untrusted receipt is forbidden. A caller that cannot authenticate the issuer
must fail closed before entering the evidence store.

## Consumer and terminal-observer binding

The target ports name control engineering/runtime and learning evaluation/operator/
plasticity consumers. Each consuming product path must name its actual host and
terminal observer. Examples of acceptable observer ownership are:

- evaluator-owned terminal evaluation outcome for evaluation claims;
- provider-owned status lookup or signed acknowledgement for provider effects;
- independently administered operator/reviewer ceremony for independent decisions;
- current revocation/tombstone owner for artifact or consent invalidation.

A dispatcher, queue, policy decision or successful store append cannot self-label
a remote or independently governed terminal outcome.

## Current blocker

The repository has source-complete qualification primitives, but the registered
learning/control modules that should produce or consume these qualification
records are themselves still marked not product-composed. Therefore this document
does not flip `productionImplementation`, `productExecutionProved` or
`productionWriterState`. Those claims change only in the exact candidate that
adds a real authenticated product callsite and product-host execution receipt.

## Completion evidence

The production-composition receipt must name the code callsite, process/image,
configuration/body generation, store path/owner, issuer authentication source,
single-writer/fence semantics, terminal observer, revocation source, fault tests,
target-host measurements and rollback predecessor. It must also contain all
eighteen canonical module execution-receipt fields.
