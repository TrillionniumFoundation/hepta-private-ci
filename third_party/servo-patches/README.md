# Servo source pin

The browser boundary is evaluated against Servo commit
`84bcc9ac701874fa9819e5cdee06356b961d736c`. This directory intentionally
contains no automatically applied patch and grants no network, deployment,
promotion or release authority. Any future patch must be digest-bound and pass
the same browser qualification gate.

`WORKER_CONTRACT.json` records the current fail-closed Hepta worker contract for
this pin. It is a contract only: the current tree still does not contain a
qualified Servo worker artifact, OS sandbox or target-host isolation evidence.
The corresponding implementation/security decisions are documented under
`docs/modules/browser.servo/`.
