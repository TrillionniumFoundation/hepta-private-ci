# Unwired Objective source custody

State: **SOURCE_ONLY_HOLD**. These two files retain the exact source bytes and
100644 modes from commit 03ec884b593e870e8c07f53815e62a387bd50170; MANIFEST.json
records their original paths, Git blob identities, lengths, and SHA-256 hashes.

At that source, neither file is declared by the Agentd library, binaries, or a
source include. The reviewed active code, scripts, workflow and tool sources reference these
module names only inside the two historical files themselves. They require older Objective APIs that
are absent from the current intelligence crate. Keeping them under src made
the Lane E inventory report their legacy journal trait and read-only V1 event
matches as if they were product writers.

The actual product path remains objective_runtime.rs and its
objective_submission.rs module. It uses the signed Objective admission and
typed RunStart publication owner. This move does not add a recovery API, restore
the old APIs, change that current owner, or qualify the historical implementation.

Do not compile, include, generate from, or register these custody sources as
product modules. A future restoration needs an explicit API and authority
review, normal source integration, and owning validation. The Lane E guard
rejects direct source imports from this custody location and unproved
non-literal source includes. It is a bounded source check, not a Rust macro
expander, runtime attestation, or proof about arbitrary build-script output.
