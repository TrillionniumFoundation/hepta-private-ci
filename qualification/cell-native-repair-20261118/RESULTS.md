# Completed native-turn and retrieval comparison

All **88 model calls, 44 two-step graphs, 88 task verifications and six training
reference verifications completed**. The original owner waited for the real
child's exit code 0 after 424.419 seconds; no timeout or forced termination
occurred. The provider retained all 88 responses and closed normally.

The source was frozen at `ad73c100feece91c152a96ba121d2e9494f10607`, and the
pre-generation freeze digest is
`d0c4c178bcd9ebd2d82e1a51dc3c7ca4da4a70ee2c148d1e701469c995e22640`.
The four previously exposed diagnostic tasks were not used for training.

| Arm | Selected success / 4 | Last success / 4 | Recovery | Regression | Format rejections / 8 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original bundled FF | 1 | 0 | 0 | 1 | 4 |
| Original bundled TF | 0 | 0 | 0 | 0 | 4 |
| Native FF | 1 | 1 | 0 | 0 | 2 |
| Native TT | 1 | 1 | 1 | 0 | 2 |
| Native CC | 0 | 0 | 0 | 0 | 7 |
| Native TF | 1 | 1 | 1 | 0 | 2 |
| Native CF | 1 | 1 | 1 | 0 | 6 |
| Native TF without answer | 1 | 1 | 1 | 0 | 4 |
| Native TF without feedback | 1 | 1 | 1 | 0 | 2 |
| Native FF with retrieval | 0 | 0 | 0 | 0 | 6 |
| Native TF with retrieval | 0 | 0 | 0 | 0 | 3 |

Native turns reduced format failures for FF and TF and eliminated FF's observed
second-call regression. TF recovered one task, reaching the same 1/4 success as
strong single-model FF and TT. Removing either TF message still left 1/4 success.
The observed improvement therefore supports the interface correction; it does
not establish a capability advantage or communication necessity for the Circuit.

Both retrieval arms received byte-identical initial reference messages. Adding
the selected old A reference reduced each to 0/4. FF input tokens rose from
3,122 to 5,732; TF input tokens rose from 2,970 to 5,723. This particular reference
policy introduced interference and additional input work. The full run used
38,379 input tokens and 4,848 output tokens. It performed 46 actual business-test
executions; the remaining 42 generation outputs failed format admission.

## Original evidence and independent readback

`READOUT_SOURCE.py` checks every frozen graph digest, actual per-node request,
output and semantic verification; reconstructs first/last/selected business
outcomes; verifies the assistant action and stable feedback at the receiving
Cell; and proves both retrieval arms consumed the same initial messages. It
made zero model or business-verifier calls.

`RAW_EVIDENCE.tar.xz` preserves 977 members. After transfer, all 975 original
index entries were independently checked for byte length and SHA-256; the two
additional members are the index and readout. Archive SHA-256:
`67f23a8207971e9b41c80483e07b7b08a94b99027bd24998bae89bd953d1cbb7`.
The archive includes source, deployment, freeze, retrieval, all 44 graph and
88 node originals, raw provider stdout/protocol, and real owner/provider exits.

The owner measured 410.766 user CPU seconds and 15.482 system CPU seconds for its
child and waited descendants. Nested process and per-call timings overlap.
Energy and monetary observations remain unavailable, so these counters do not
constitute complete system cost or equal actual budgets.

## E5 source status

`E5_SOURCE_READOUT.json` binds the current input files: six authorized curated
training records from one project, and six new public upstream evaluation-only
records from three repositories. The new records are not authorized as training
inputs. The authenticated user count remains zero. Fixed-total and
fixed-per-source user-growth curves require actual authorized usage sources;
renaming these records or training on the evaluation targets would not supply
that evidence. No growth curve was fabricated from this comparison.
