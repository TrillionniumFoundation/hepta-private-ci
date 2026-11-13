# Rama crypto 0.3.0 time compatibility backport

This retains the exact published Rama crypto 0.3.0 Rust implementation, API and features, with original archive and license identities in HEPTA-PATCH-PROVENANCE.json. Only the two time constraints become exactly 0.3.55. The original workspace's temporary 0.3.47 pin addressed time-rs/time issue 783, the 0.3.48 coherence regression fixed by 0.3.49. Rama upstream removed the workaround and selected 0.3.55 in commit 4ba2015fce25609d1cf54722059f330fdfafc62c (PR 1220). We retain an exact 0.3.55 bound for the reviewed Matrix upgrade graph.

This is separate from the previously validated Smithy pin-utils backport. Matrix crypto 0.19.1 requires time 0.3.55, while the unmodified Rama release makes that graph unsatisfiable. The final candidate must validate actual certificate/CA network paths and encrypted Matrix migration on the same locked graph. No audit policy is suppressed and no Rust crypto implementation is edited here.
