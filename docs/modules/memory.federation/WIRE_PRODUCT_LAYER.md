# memory.federation canonical V2 product adapter layer

This stacked delivery binds the authenticated durable wire host/client to the canonical memory.federation V2 query and response contracts.

## Included

- bounded canonical V2 query and response body encoding;
- body digests bound to authenticated wire frames;
- exact-attempt response preflight before replay or terminal mutation;
- authenticated transport-context issuer/verifier binding local owner, remote peer, profile, channel lifetime, and key generation;
- product client and read-only host adapters;
- interruptible single-attempt transport with deadline and final local-use fences;
- same-process and restart retry safety when inbound persistence fails;
- contention, body-tamper, wrong-attempt, clock-regression, cancellation, atomicity, and capacity-probe tests.

## Excluded

The crate remains transport-neutral. This layer does not select mTLS/QUIC, provision deployment credentials, compose Agentd serving, operate two independent real hosts, establish target SLOs, or grant independent acceptance, activation, promotion, or release.
