# memory.federation authenticated wire protocol core

This delivery layer isolates the transport-neutral security protocol from host recovery and product composition.

## Included

- canonical registered query, response, cancel, and cancel-ack framing;
- directional credential enrollment, strict-generation rotation, expiry, and revocation;
- HMAC-SHA-256 frame integrity and operating-system nonces;
- immutable verified-frame values;
- bounded fail-closed replay admission with per-credential isolation and clock-regression rejection;
- authenticated owner-frontier witnesses;
- bounded cancellation-attempt state and typed acknowledgement.

## Excluded

This layer intentionally contains no durable replay/attempt store, read host, outbound client, filesystem backend, selected mutually authenticated network transport, secure deployment credential provider, Agentd composition, real-host qualification, activation, promotion, or release claim.

The next stacked layer owns durable host/client recovery. Product packet and canonical V2 transport adaptation remain in a later layer.
