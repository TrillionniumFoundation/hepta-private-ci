# Binary peer qualification: first registered attempt

## Result

All eight controls passed at frozen source `d22af9a1b1875d60fd685349ecc87ecb73a297b4`
after prospective protocol `8ed5df4986f2cd605bb3b8d5cce12225f795f2ba`.
Base: `fd5fabec7b52ce7eb943e69f4d8e9fee23777bec` (lossless codec #7205).
The process exited 0: zero failures/errors, 4.595080907 seconds inside the
suite, 4.879940319 seconds observed by its 90-second outer supervisor.

Four retained JSON controls passed against this changed source. The four new
binary controls passed complete message round trips and seven malformed
cases, actual four-process directed-cycle propagation, exit 71 after durable
commit with same-database replay, and explicit mixed-profile refusal.
JSON remains the default; the old `pft_peer.py` is untouched.
Both cycle controls produced identical complete candidates across their four
peers; maximum error against independent augmented least squares was
5.342948306008566e-16, under the fixed rtol=atol=1e-7 threshold.
The small fixture offer used 699 encoded body bytes versus 1,569 original
canonical JSON bytes. This fixture is not a network or training benchmark.

## Implementation and evidence

The optional contract-bound codec shares the original ledger and peer state
machine. Raw frame helpers preserve the actual 8 MiB limit and shared absolute
two-second header/body read deadline. Decoded canonical requests retain their
original digest. No automatic profile negotiation or fallback is introduced.

`DEPENDENCIES.json` pins unchanged dependencies by Git blob and SHA-256.
`attempt-1.tar.gz` contains the first raw log, full results including child
PID/address/exit records, frozen invocation and source bytes, protocol,
formatting observations, final source and SHA-256 inventory.
Archive: 30,920 bytes; SHA-256 `455d7337d5c96b933d954e60978b892a8811a6678dbefafa27622b24f3dbe21a`.
The initial partial formatter capsule lacked `codex-rs`; its setup error is
retained. After copying existing exact formatter support, official `just fmt`
and Ruff 0.15.13 completed. All three changed files have equal before/after
ASTs. Tests were not repeated after formatting.

## Scope

This is an engineering result on unauthenticated IPv4 loopback. It establishes
neither source authenticity, useful-work rewards, model improvement, learned
circuit topology nor training acceleration. Original-cache network traffic
is a separate prospective scope; no historical science budget, DEV/final
samples or user traces were consumed here.
