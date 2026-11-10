# Canonical test roots on the PERC candidate

Reuse six exact-source test-only deltas from #5618 on #5663. The temporary directory already exists; canonicalize it before constructing the strict owner layout. Production path guards, reservations, recovery rules and assertions stay unchanged. The outbox test is absent on this candidate and is excluded. The LF fixture rule is already integrated in #5660.

All six current parent preimages match the reviewed originals. On isolated native Linux Rust 1.96.0, required `just fmt` preserved all seven reviewed postimages (including the LF rule), and the PERC cross-language fixture passed 1/1 with 200 unrelated tests filtered. This does not substitute for native Windows.

Automation circuit tests did not execute: build stopped in aws-lc-sys bindgen because standard C header stddef.h was not discovered by libclang. The actual first /tmp setup failure and repaired nextest installation are retained separately. A verified-header-path retry uses the original continuation identity. Agentd tests and full hosted CI remain pending. No dependency, cryptographic option, production permission or gate was weakened.
