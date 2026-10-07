# PoN boundary repair, 2026-10-08

Source base: f4165797e3a96a0a9d2b566e84c48880d2dfff29 (PR1437).
Inherited bounded exchange: 32740b3662dcffdd905a1095d3ee7f402d9def13 (PR1434).

The existing Agentd host now uses the bounded asynchronous pipe exchange with
one original deadline and equal stdout/stderr bounds. Started-but-uncertain
work remains Unknown. Original exact effect/payload binding and signed
depth/work confirmation policy remain intact. Native observation parsing now
recomputes height depth, checks active-tip identity and requires positive
work distance for a distinct active ancestor. Oversized bytes reject before
adapter-owned copies. Tests cover full/blocked input, both output limits,
incomplete JSON, nonzero exit, inherited output pipes and contradictory
observation fields. Historical tests are adapted to the current v3 shape;
historical success is not inherited.

Validation must run on this delivered source: just fmt; just test -p
codex-hepta-agentd; just test -p codex-hepta-agent-protocol; scoped Clippy and
the ordinary architecture/required CI. Source materialization is not a test.

Remaining obligations are explicit: binary hash-to-execution object binding,
independently current artifact/withdrawal/selection/final-use checks, real
installation and three-generation consumer benefit. Chain owner_generation
is not a Hepta final-use generation and cannot be compared by casting them.
No second journal, supervisor, trainer, or registry is introduced. Model
parameter adoption does not authorize neuron code/topology replacement;
neither authorizes a consensus/verifier upgrade. Such upgrades require their
existing distinct authorities and fresh explicit protocol contexts.

Physical power loss, independent WAN operators, sustained public capacity,
and model efficacy are not claimed by these local pipe fixtures. No release,
production, branch protection or deployment setting is changed.


## Sealed-byte execution continuation

The PoN adapter now executes a held Linux sealed image from the existing
provider byte-identity contract. The same nonblocking/no-follow source
descriptor is type/permission/length checked, copied within a fixed byte
bound, and closed. The copy receives write/grow/shrink/seal seals before
its actual bytes are SHA-256 checked. Only a read-only descriptor remains
at execution. Atomic path replacement and same-inode rewriting cannot
change the held image. The host keeps that image through the bounded
child exchange, under the original operation deadline. No key, journal,
global cache or process supervisor is introduced. Existing rustix/sha2
dependencies in the contracts crate are reused; Cargo/Bazel dependency
graphs are unchanged.

This PoN local provider now requires Linux memfd sealing and access to its
host proc descriptor path. Unsupported systems reject before provider
contact rather than silently executing a mutable path; the HTTP provider
is unchanged. Linux-specific process fixtures cover the implemented route;
a separate contract test requires Unsupported on other platforms. Dynamic
libraries, script interpreters, environment, local ptrace privilege and
the kernel remain trusted. This binds executable bytes, not all execution
dependencies and not Chain storage or current Hepta final-use authority.
Blocking filesystem syscalls are not made physically preemptible by the
between-chunk deadline checks. Real device/OS acceptance remains separate.
