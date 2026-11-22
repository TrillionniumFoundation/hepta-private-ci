# #6940 immutable artifact readback

This directory preserves the exact 13,897,893-byte Actions artifact from the
single admitted execution of Draft #6940. The 28 ordered parts reconstruct the
original ZIP with SHA-256
`2ecc44ac2d769105908e1b44b5bfabb99713c791b45c237da48913847af9de41`.
The archive has 22 members: `HOST.json`, `RESULT.json`, and 20 canonical
checkpoint payloads.

Actions 44988986473/job 137105680797 succeeded. The numerical step consumed
333.682125633 wall seconds, 333.660534273 CPU seconds, and 67,108 KiB maximum
RSS. The 20 cursor payloads total 46,000,720 bytes. All ten index-64 payloads
are 1,493,867--1,543,224 bytes; all ten index-128 payloads are
3,023,330--3,138,734 bytes. Both the 8 MiB per-cursor and 64 MiB aggregate caps
held at these two boundaries.

`verify_readback.py` is a zero-recurrence byte audit. It reconstructs and tests
the ZIP, checks every member digest and size, validates canonical JSON/body
hashes and canonical signed lowercase hexadecimal fraction syntax, and checks
the frozen identity, work ledger, costs, and fail-closed scope. It executes no
row action, tail check, provider, dynamic, exponential, Torch, or optimizer
work.

This evidence remains a resource profile only. It does not reach the first
possible authentic tail check at index 537 and does not close resource
admission, tail termination, unique rounding, provider completion,
arbitrary-history resume, N256 qualification, C2 full replay, HPCA custody, or
production adoption. #6939 remains `RED_DECIMAL_INTEGER_DIGIT_LIMIT`; earlier
RED and UNKNOWN results remain unchanged. Global HOLD / `all_closed=false`.
