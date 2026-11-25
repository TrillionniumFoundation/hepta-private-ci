# Original paired human inspection

This component adds current human inspection to the existing open-only paired
Root owner. It is source-defined engineering work. It does not install a new
production lane, authenticate a new participant, return a material permit, or
read training material. Generic paired FinalUse requests still fail before mint.

## Owner and lock order

`HostAuthorityService::observe_registered_paired_human` borrows the two handles
already installed by the original trusted UI and physical-login composition.
Both must exist. The borrowed value retains one absolute deadline; constructing
or retaining it does not grant permission for a later read.

The original issuer, writer, paired effect and independent enrollment are then
checked by the same Registry object and its existing four-record mutex boundary.
Inside that callback, the order remains Registry, issuer request lock, retained
issuer state. No asynchronous operation occurs while these locks are held.

The new pure predicate checks the loaded state, including the current text
policy, retained signature envelope, human scope, namespace, generation, payload
and expiry. It cannot call the complete human verifier or reacquire its issuer
lock. The original public text verification path delegates to this predicate
under its own original request lock and retains the original UI owner checks.

Paired inspection also binds the canonical signed delivery, exact consent
purpose, principal, permission revision and original route. It rechecks both
original held descriptors, observes the original issuer clock after those OS
calls, and checks all four lease expiries again before returning metadata.
Missing, revoked, changed or expired dependencies are rejected without changing
the Registry frontier, issuer counter or retained signature record.

## Engineering controls

The existing Linux source-head gate retains its nine ordinary paired controls
and adds seven named controls; its minimum becomes 16. The separately ignored
Root service refusal remains a separate one-test gate and is not included.

Five new controls use an actual temporary Registry, issuer key/signature CAS,
retained writer proof and reopen path. They cover unchanged observation, changed
delivery or principal, current text-policy removal under the original lock,
retained-signature expiry after reopen, and independent enrollment revocation.
Two controls use actual kernel self-pidfds to check that both borrowed handles
and exact bindings are required and that the original deadline is not renewed.
Their UI/login metadata is explicitly synthetic; they do not validate physical
login enrollment or manufacture production human provenance.

## Remaining consumer boundary

The public observation carries no opaque receipt, grant, callback or read right.
The private fresh preparation continuation from the earlier stage is unchanged.
A fixed material owner, its durable exclusive first-entry record, the real peer
request, and synchronous first read still need to be connected to this same
boundary. A later implementation must repeat the live checks at that actual
entry, consume the original private continuation once, and retain an uncertain
entry across restart or a lost reply. This stage does not enable dispatch or
relax the Python owner intake rejection.
