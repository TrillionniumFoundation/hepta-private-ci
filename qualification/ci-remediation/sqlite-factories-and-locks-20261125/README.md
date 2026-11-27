# SQLite fixture and dependency closure

The actual Windows main-CI failures included SQLite 4618 when a stock
inspection connection joined an already-open private evidence store. The
unchanged native VFS explicitly refuses this mixed shared-memory policy.
Seventeen inspection/tamper/blocker call sites now use the same private
factory as their real stores. SQL statements, hostile mutations, transaction
locks, and owner/identity assertions remain unchanged.

Two copied-database tests now initialize and close a real private destination
then replace its entire contents with the closed source image, checking exact
byte equality. They retain the cross-Agent AccessDenied assertion and print
the actual error if it fails. The previous logs hid that error, so the
operating-system ownership explanation remains a fixture hypothesis pending
the next Windows run; this receipt does not claim those tests passed.

The two exec resume fixtures use a centralized connection restricted to the
configured existing primary state index. It preserves the original options:
creation disabled, foreign keys enabled, no journal/timeout override. The
disabled lexical evidence-recovery API is unchanged. Two actual Linux
workspace regressions passed; 214 other state cases were outside the explicit
selector. Scoped just fix and strict just clippy both exited 0 without source
changes. Existing dependency warnings are retained in the logs.

The first local test build failed because the new test used an undeclared
tempfile dependency. It now reuses state fixtures and scopeguard. The next
run exposed an invalid fixture journal-mode transition while its pool was
open. The final fixture closes the pool before setting the journal mode on
one connection, then reopens through the production factory and verifies
journal preservation and foreign-key enforcement. All attempts are archived.

Production Cargo retains the same 1,532 package identities and all external
versions/checksums; only three first-party Windows dependency edges changed.
The separate Dylint lock was resolved with the original nightly and pins all
Dylint components to 6.3.2. Bazel 9 regenerated its lock and the original drift
check passed. Its initial embedded-JDK trust failure was resolved by using
the existing platform trust roots, with TLS validation kept enabled.

Cargo-deny 0.19.0 against RustSec 10db6998 reported zero errors in advisories,
licenses, bans and sources. Existing warnings and nine original advisory
exceptions remain visible and unchanged. The original C refusal guard,
security policy and authorization gates are unchanged. Full native and main
CI qualification still belongs to the next published source.
