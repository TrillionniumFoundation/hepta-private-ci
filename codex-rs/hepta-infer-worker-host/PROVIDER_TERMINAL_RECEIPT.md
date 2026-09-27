# Signed provider terminal and usage receipts

## Purpose

A signed provider receipt is a recovery input for one already durable hosted
App Server dispatch. It is not dispatch authority, retry authority, billing
settlement by itself, or proof that the owning Agent remained authorized.

## Signed claims

Schema `hepta.provider-terminal-receipt.signed.v1` binds:

- issuer, authority epoch, receipt ID and validity interval;
- durable request ID, principal and worker generation;
- model, provider, thread and turn identities;
- runtime.codex request, payload and source-admission digests;
- terminal-correlation digest;
- terminal status and exact output bytes plus output SHA-256;
- optional cumulative output-token observation;
- bounded stop reason and semantic digest.

The verifier pins one issuer, Ed25519 public key, authority epoch and maximum
receipt lifetime. Unknown fields, invalid identity/digest syntax, semantic
drift, invalid signature, wrong epoch, future issue time, expiry and excessive
validity fail closed.

## Application rules

`resolve_with_provider_receipt` compares every signed execution field with the
existing durable request and dispatch. It rejects pre-dispatch stops, App Server
rejections, request/thread/turn/provider drift and runtime.codex digest drift.

The normalized `NativeRunOutput` preserves the existing
`NativeOwnerAuthority`. When no owner observation exists it remains
`Unverified`; a provider receipt cannot create `ObservedReady`.

The native journal already enforces monotonic refinement:

- a previous terminal status, boundary, output and correlation cannot change;
- cumulative usage cannot decrease or disappear;
- an indeterminate observation may become exact terminal evidence;
- a terminal observation with unknown usage may later gain usage;
- unknown usage is never encoded as zero.

## Evidence retention

The journal stores normalized execution facts. The receipt archive must retain:

- the original signed receipt bytes;
- signer/key and authority-epoch provenance;
- the verifier configuration;
- the returned receipt witness SHA-256;
- receipt acquisition and application time;
- the exact source and binary identity that applied it.

Receipt archive retention must outlive the associated journal and financial or
incident-audit horizon. Restoring an older receipt archive or verifier epoch is
an external anti-rollback failure and must not be silently accepted.
