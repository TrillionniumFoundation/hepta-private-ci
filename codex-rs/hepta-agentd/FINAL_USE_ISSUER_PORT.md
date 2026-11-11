# Agentd final-use issuer transport

`AgentdUnixFinalUseGrantProvider` implements the existing
`AgentdFinalUseGrantProvider` seam for the original production writer. It
transports an original `FinalUseBinding` to an independent issuer and returns
the original `SignedFinalUseGrant`. It owns no signing key or durable state and
does not replace the writer, outbox, FinalUse verifier, or Notes destination.

## Trusted host composition

The embedding host constructs the provider with `from_stream(stream, peer,
timeout)` and supplies it to `AgentdProductionOperationRuntimeConfig::new` or
`AgentdProductionWriterHost::attach_target`. Normal Agentd CLI startup does not
discover or install this capability.

The host must obtain the already connected private Unix stream through an
independently bounded, authenticated bootstrap. It transfers exclusive
descriptor ownership and pins the expected issuer UID and PID in
`AgentdFinalUseIssuerPeer`. The adapter checks Linux `SO_PEERCRED` before any
request. The credentials identify the peer at connection/socketpair creation;
they do not prove who holds subsequently duplicated descriptors. Issuer process
isolation, descriptor custody, and a bounded connection bootstrap remain host
responsibilities. No filesystem socket path, environment lookup, connection,
reconnection, subprocess signer, or key generation occurs in this adapter.

The issuer must explicitly support operation
`runtime.agentd.production_operation` and decide whether the exact original
binding may receive a grant. A `runtime.codex.turn_start` approval is not
relabeled or widened to authorize a device effect.

## Wire and authority boundary

The transport reuses the existing independent authority port's schema-v1
u32 big-endian length framing and JSON field shapes:

```text
request  = { schema_version: 1, operation, binding: FinalUseBinding }
response = { schema_version: 1, revocations: FinalUseRevocations,
             grant: SignedFinalUseGrant | null, denial_reason: string | null }
```

Exactly one response outcome is required. Requests are bounded to 16 KiB and
responses to 64 KiB; the response length is checked before allocation. Unknown
fields, trailing JSON, unsupported schema, invalid grant shape, a mismatching
binding, truncation, and overlong denial messages fail closed. Issuer prose,
request bodies, and signature bytes are not returned as diagnostics.

The response's unsigned `revocations` field is parsed only for wire
compatibility. It cannot update the original authority's independently
configured revocation head. The original FinalUse authority still verifies
signer/key, signature, exact binding, the configured clock, authority epoch,
revocation state, nonce replay, and durable admission before the original
destination dispatcher can enter an effect. Receiving a grant is not effect
authority and is not a completion receipt.

## Deadline, capacity, and uncertainty

The configured timeout must be nonzero and at most 30 seconds. All request
writes and response reads share one monotonic deadline; each partial transfer
recomputes its remaining time. Progress cannot restart the timeout. Waiting for
another request's mutex is prohibited: a concurrent request receives `Busy`.
The deadline begins when the provider runs; it does not include time queued in
Tokio's blocking pool and is not an end-to-end 30-second service guarantee.

The original writer host runs synchronous provider calls on one blocking worker
per attached host, shared by its clones and destinations. The worker owns its
capacity permit until the provider returns. Cancelling the waiting future
cannot release capacity early or create an unbounded sequence of abandoned
workers. External implementations of the provider trait must also bound their
synchronous work; this transport returns within its own I/O deadline.

A complete denial can leave the channel available for a later, separately
requested authorization. An uncertain or invalid exchange permanently closes
the channel and never reconnects or retries. The writer's existing
pre-boundary reauthorization rule remains separate from transport behavior;
unknown effect rows remain observation/reconciliation only. Notes receipt
recovery uses its existing independent lane and never requests another grant.

## Deployment inputs and acceptance

This implementation supplies a transport adapter, not a deployed issuer or a
production qualification result. The seven source-profile requirements remain:

| Input | Required independent source |
| --- | --- |
| Production grant provider | Authenticated issuer descriptor, exact peer, supported operation and issuer policy |
| Protected authority clock | Qualified host `AuthorityClock`, not a compatibility clock relabeled as protected |
| External authority frontier | Durable external CAS frontier surviving local-directory rollback |
| Trusted issuer keyring | Independently pinned public keys and epoch windows; private key stays outside Agentd |
| Revocation head | Authenticated current head and distribution/freshness policy, independent of this reply |
| Recovered writer configuration | The original recovered writer, exact lease, generation, and live authority verifier |
| Current-cut authorization state | Independently authenticated current recovery cut; no writable-store fallback |

The ordinary package gate is `just test --locked -p codex-hepta-agentd`.
Focused tests cover real private socket exchange, peer mismatch, oversized and
truncated frames, binding mismatch, partial-progress deadline exhaustion,
concurrent requests, original signature verification and nonce replay, and
preservation of the original revocation head. The worker cancellation test
checks that its capacity remains occupied after its waiter is cancelled.
Test keys and compatibility clocks in those fixtures are explicitly isolated
qualification inputs; they are never production inputs.
