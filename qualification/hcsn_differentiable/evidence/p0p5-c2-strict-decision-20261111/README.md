# HCSN C2 successor execution-decision strict admission — HOLD_NO_GO

This distinct candidate is based on Draft #6005 exact head 93b8b9175a9c40e2e50e438de35c099a3ea6d7b8.
Only the **prospective** C2 run decision was hardened: byte-identical ambiguous JSON with
duplicate keys, NaN, surplus metadata, missing/wrong version, symlinks and oversized files
must fail closed. The decision payload is now a fixed six-field versioned schema. This is
a stricter future input contract; existing historical C2 did not have such an authorization,
and none has been minted by this change. SHA pinning alone is not independent authority.

Synthetic RED on unpatched parent: 8 tests, 7 failing assertions, exit 1
(job 1a1cc0085b4-2564-da6).
Native GREEN: 8/8 new and 32/32 combined successor tests,
0 failure/error/skip, exit 0 (job 1a1cc0181f8-2564-da9).
Python 3.12.3, Torch 2.8.0+cu128, CUDA devices hidden.
Original C2 run 1a1c74f3308-be2a-75 was not restarted or changed. No new full
training, independent model replay, scientific comparison, production GO or P0–P5
closure is inferred from synthetic unit tests.
EVIDENCE.json records the retained log byte lengths, sha256 and denominators.
