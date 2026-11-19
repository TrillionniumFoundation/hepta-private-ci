# Exact turn finish fixture qualification

The shared test helpers now observe the exact completed turn's existing finish
owner before submitting another operation. The whole wait stays within each
original 10s/30s event budget; production admission is unchanged.

The four original compact/deferred/settings/permissions focus cases and three
finish observer cases passed. The identical helper source then passed all 48
related cases in one run, with zero retries (76.014s test execution).
Scoped fix and format completed afterward without changing tested helper bytes.

Earlier 45/48 output and the real original 5s builder timeout diagnosis are
retained. They are not erased by the later scoped pass. This is no package-wide,
whole workspace, Rust1.96 final-source or native recovery qualification.
The [publication index](publication.json) records every original byte hash.
