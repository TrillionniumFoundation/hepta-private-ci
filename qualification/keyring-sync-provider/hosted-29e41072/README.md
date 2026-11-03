# Hosted compatibility evidence for the rejected entropy source

Exact source: `29e41072ce0d097acfd59b5ecc1fdb525e45d75e`.
Workflow run: `41669578892`. Native job `126034062498` and Bazel job
`126034063179` both completed successfully. The checks exercised the original
C identity assertions, the pinned static D-Bus client, 12 actual old/new
credential stages including restart recovery and rejection of DH without a
plaintext retry, and all 15 original secrets tests. The service trace recorded
17 encrypted DH sessions and zero plaintext sessions.

The Bazel job generated the real lock, passed the original lock check, executed
the native identity test, and built the keyring-store library. Its generated
lock SHA-256 is
`b11c6619f6f251309ded623763280cdce702c1813f2ce53dd982336e81eda54e`.
It was not adopted as the final successor lock because the provider graph then
changed for the entropy repair.

These are compatibility results for this exact old source. It remained
**SECURITY HOLD** because official dbus-secret-service 4.1.0 used fastrand for DH
private bytes and IVs. None of these results is transferred to the repaired
successor. Full workflow artifacts are identified and hashed in the receipts.
