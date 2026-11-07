# Matrix SDK event-handler type-map patch

Source: crates.io `matrix-sdk 0.19.1`. RUSTSEC-2026-0319 identifies its
anymap2 dependency as unmaintained and recommends anymap3. Replace only that
manifest dependency with exact anymap3 1.1.0 and update the event-handler map
imports/type aliases. Native targets retain Clone + Send + Sync requirements;
Wasm retains CloneAny without Send/Sync. The map still stores one value per
concrete type, replaces same-type context, and clones context on extraction.

No encryption, authentication, serialization, SQLite migration or transport
implementation is changed. The SDK's upstream crypto0.19.1 fixes0318. The
patch is tested through real SDK event handlers and the isolated Synapse SDK
qualification; the original paired-host acceptance remains a separate gate.
