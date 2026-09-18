# Servo source pin

The Browser/Servo qualification candidate is evaluated against Servo commit
`5cc5bd32d02619acdec5736055515e38c5840ce1`. Its predecessor was `84bcc9ac701874fa9819e5cdee06356b961d736c`.

The selected candidate includes upstream WebView/input-event deadlock fixes
landed after the predecessor pin. The delta is broad (239 upstream commits), so
selection is not qualification: the exact-head worker build, real Browser E2E,
reproducibility/SBOM gate and reviewed committed Cargo.lock must all pass before
deployment evidence may consume this pin.

This directory intentionally grants no network, deployment, promotion or release
authority. Any patch or future pin change must be digest-bound and pass the same
Browser qualification gate.
