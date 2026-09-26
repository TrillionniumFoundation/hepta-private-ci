# Servo source pin

The Browser/Servo qualification candidate is evaluated against Servo commit
`b5a1f5e6ec6f8685d40cd389802ced7abe4980f6`. Its immediate predecessor candidate was `5cc5bd32d02619acdec5736055515e38c5840ce1`.

The 13-commit delta intentionally absorbs upstream `07777aaa...`, which fixes
a general libservo double-borrow hazard and changes `WebView::load()`, a direct
Hepta worker callsite. The delta also changes Servo's Cargo dependency graph, so
selection is not qualification: the exact-head worker workflow must generate the
new candidate Cargo.lock, that exact lock must be reviewed and committed, and
then locked compile/tests, real Browser E2E, reproducibility and SBOM evidence
must all pass before target deployment qualification may consume this pin.

This directory intentionally grants no network, deployment, promotion or release
authority. Any patch or future pin change must be digest-bound and pass the same
Browser qualification gate.
