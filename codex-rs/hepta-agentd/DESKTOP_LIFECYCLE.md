# Original Desktop owner succession

The Notes and Calculator candidate retains the original Root, authority lease
registry, issuer, CognitiveStore and durable writer. This increment adds one
original-issuer operation: both application policies move in one full issuer
state compare-and-set. It does not enable the product recovery CLI or extend a
live lease.

## Owning implementation

- `deployment_desktop.rs`: `RootDesktopPolicy` binds one Session's Notes and
  Calculator targets and a bounded grant lifetime. The actual Root entry
  `replace_registered_desktop_policy` accepts an already registered successor.
- `deployment_writer_rotate.rs`: the existing original writer succession
  validates a retired predecessor and its exact live successor.
- `authority_host_session_material.rs`: the existing Root session recovers
  protected physical Current and retains the original owner.
- `deployment_desktop_tests.rs`: real original registry, signer and disk CAS
  component tests. Synthetic target identities do not qualify a live Session.

The trusted launcher must establish old publisher exit, legal local lease
release or actual expiry, original writer authorization rotation and physical
Current adoption before calling this policy transition. The new Session's
credential-checked reservation supplies both successor targets.

The transition verifies the live original writer and retained proof under the
original locks. It accepts either the exact complete predecessor pair or the
already-published exact complete successor pair. A mixed or ambiguous pair
refuses. The same CAS preserves every other policy, signing key, sequence,
revocation head and writer proof. Old signed receipts keep their original
meaning; this operation never dispatches an effect or renews an old request.

An error can follow a durable publication. Only the same successor pair may be
reconciled. A new pair is a new administrative decision, not an automatic retry.

## Remaining composition

The existing product remains a finite session. Live lease renewal, a recurring
original Root successor supervisor, joint recovery launch fields and Calculator
physical application-state recovery have not been enabled by this increment.
The Notes-only recovery profile must not be relabeled as joint recovery.

A subsequent joint launcher must first consume original physical Current, use
the actual successor Session reservation, invoke this atomic policy transition,
recover old app results without writable replay, then publish the joint runtime.
Every unknown result keeps its original operation and target identity.

## Verification

Use Rust 1.96 and the original entry point:

```text
just test -p codex-hepta-agentd --lib deployment_desktop --locked --offline --test-threads 1
just test -p codex-hepta-agentd --lib deployment_notes --locked --offline --test-threads 1
just test -p codex-hepta-agentd --lib deployment_writer_rotate --locked --offline --test-threads 1
just fix -p codex-hepta-agentd
just fmt
```

These commands define validation scope, not an execution claim. Ordinary owner
fixtures do not establish protected Root custody, final installed-product,
same-boot joint recovery, cross-boot recovery or native Asterinas qualification.
