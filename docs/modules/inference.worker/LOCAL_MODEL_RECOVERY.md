# Experimental local-model recovery boundary

This document specifies the recovery contract for the feature-gated
`experimental-local-model` profile. It is repository source design and does not
establish a real weights/device driver, target-hardware qualification,
production composition, independent acceptance, activation, promotion or
release.

## Capability split

`DurableLocalModelWorker::run` and `DurableLocalModelWorker::recover` have
different authority:

- `run` requires the signed resource grant to be current. It may reserve a new
  exact operation and, after durable prepare, enter the physical driver once.
- `recover` does not authorize a new physical effect. It requires an already
  persisted operation that may have entered the driver and may call only the
  driver's `inspect` operation.

Expiry or revocation therefore prevents new model execution without preventing
observation and containment of an effect that may already have occurred.

## Exact recovery identity

Recovery binds all of the following to the existing durable record:

- stable request identity;
- worker subject and generation;
- signed grant witness;
- verified model-manifest semantic digest;
- attested driver handle and resource-attestation digest;
- verified input digest;
- original token, usage, transient-memory and deadline bounds;
- durable dispatch model provider and exact handle identity.

The caller must reproduce the original payload exactly. A changed input,
manifest, grant witness, handle, bound or deadline is a conflict. Recovery does
not create a replacement request under the same identifier.

## State rules

Recovery is rejected for a merely reserved request, a request stopped before
physical effect entry, or an explicit pre-entry rejection. These states are
known not to require driver inspection.

For a possibly entered request:

1. an existing terminal observation is returned without replay;
2. otherwise the worker calls `inspect(operation_id, handle)`;
3. a matching terminal observation is validated against the original token and
   usage ceilings before durable settlement;
4. pending, missing or ambiguous history remains quarantined and is never
   converted to success, zero usage or safe replay;
5. a driver `run` call is never made from the recovery path.

## Resource truth

Model load admission checks aggregate existing residency plus the independently
observed resident and transient load peak. Request admission reserves bounded
transient memory before effect entry.

A prepared request guard may roll back safely. Once a request is marked
running, an uncompleted guard drop retains its memory and concurrency charge,
quarantines the operation and fences the generation.

Terminal settlement releases a held request only when the terminal boundary is
not quarantined, or when a later independent resource observation exactly
matches the attested handle and remains within the original transient-memory
bound. Missing or mismatched resource evidence leaves the charge held and the
generation fenced.

Failed model unload never deletes the handle. It remains `Zombie` or
`RepairRequired` until independent zero-residency evidence permits removal.
When a physical load cannot be independently shown to have been cleaned up, its
reservation remains repair-held and the generation is fenced.

## Usage semantics

An absent token or usage observation means unknown, not zero. Pending and
terminal observations are checked against the original request and grant
ceilings. The current shared native journal durably retains optional output
-token observations and a terminal receipt digest that commits to local usage
semantics; a dedicated durable generic usage field is not yet a production
claim.

## Remaining product gates

The following are intentionally outside this source closure:

- a real driver that proves exact weights, tokenizer, runtime, device lease and
  physical memory;
- restart reconstruction of a real attested device handle under a named driver;
- deployed revocation distribution, trusted time and anti-rollback;
- OOM, device-reset, load-kill, unload-failure and process-crash qualification
  on named target hardware;
- independent acceptance and production activation.
