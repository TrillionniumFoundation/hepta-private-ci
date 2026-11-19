# Runtime assembly and caller-gate observations

This bundle preserves six original assets recovered from fixed GitHub blobs,
the native 23-file merge-file assembly record, and a separate observation
summary. It does not claim a complete local full-caller PASS on 5dcec or 54de.

The native assembly ran 11 real `git merge-file` operations with exit code 0.
Its 23 postimages and exact line operations are retained unchanged. The a979
preparation checkout materialized all 14,428 tracked paths, and its original
format/protected result is retained byte-for-byte: 23 formatting inputs,
no drift, 229 protected entries, and 236 boundary/inventory rows. These are
preparation results for a979, not validation results for a later commit.

The 952 formatting attempt failed and was preserved remotely. The next
5dcec attempt required that recorded failure and independently matched its
formatter output to the later frozen test blob. Its observed first stdout
event established clean formatting and protected/inventory checks for the
24-path source. The full scan was launched, but the last successful live
status was running; later status and RESULT reads timed out. No terminal
outcome is inferred from the configured 900-second budget.

The separate 54de request remains an unknown admission/execution outcome:
the start call and the parent's exact reconciliation/read calls timed out,
and no job ID or complete RESULT was observed. The immutable request is
included. Do not treat a transport timeout as a test failure or success.

`KNOWN_OBSERVATIONS.json` distinguishes preserved original bytes from
summaries of recorded tool observations. Some in-memory copies were lost
during a workspace disk-full event. Missing original outputs have not been
recreated or labeled as raw logs. Their known remote paths remain recorded.

`postimages/final25.json` records the expected final file identities, their
individual provenance, and the 54de source identity. The 25-file manifest
does not itself establish a local 54de gate result. Native results and
hosted CI outcomes are maintained separately by the root/audit agents.

Run `python3 build_bundle.py` to verify every recovered asset against its
Git blob SHA, available SHA-256/size pins, and rebuild a deterministic
`tar.xz` archive. Original file contents are included unchanged. The archive
and its index are emitted next to this directory, leaving repository source
trees and Cargo targets untouched.
