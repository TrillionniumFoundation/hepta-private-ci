# Public bootstrap type qualification

Source b64fb4403254bdfbfdba0bf69e69bede270ed96f adds the single closed public
HostAuthorityPublicBootstrapV1 shape and Linux library exports. It reuses the
original registered identity, lifetimes, writer lease/proof, checkpoint and
FinalUse frontiers. The necessary public issuer-key wrapper converts every
original trust-key field without defaults; it contains no private signing key.

The original wire/proof scope passed6/6 in0.169s, Rust1.96, with full compile
336.339s. Scoped fix124.341s and final fmt0.263s passed, final source is clean,
and no tests followed finish. This establishes compilation and those original
protocol tests; no new live bundle deployment or loader is qualified by it.

64KiB is the receiver's protocol bound constant, not a self-authenticating JSON
constructor. Trusted code must bound reads before decoding, check schema1 and
operation runtime.authority.bootstrap.v1, establish actual Root/consumer peer
lifetimes and already held pidfds through the inherited bootstrap descriptor,
and validate every purpose/binding before original client construction. Actual
consumer processes connect the five fixed lanes themselves. A Root launcher
connecting on their behalf would leave different SO_PEERCRED identity.

A real sample must be emitted from a continuously live Root service's actual
canonical issuer, retained proof, Current cut and two original frontiers. There
is no invented recovery example. [All original stage records and logs](publication.json)
retain the precise component boundary; five-lane execution remains separate.
