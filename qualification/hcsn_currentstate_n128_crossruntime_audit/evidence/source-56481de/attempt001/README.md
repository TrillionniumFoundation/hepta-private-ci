# #6291 attempt 001 exact readback — HOLD

The exact source `56481de6db8876e0b9f609b42f8819636ba757c3`
completed its sole read-only Actions attempt successfully:

- run 43361062277;
- job 131674409030;
- artifact 14008447416;
- attempt 1;
- source admission, repository format, byte audit, independent structure review,
  checkout immutability, and artifact upload all succeeded.

The audit compared all 1,151,028 original coordinate pairs and confirmed the
preserved development observation: 1,149,665 exact and 1,363 mismatched.  It
emitted 32 distinct worst-row indices, correcting only the presentation bug in
the preserved operator audit.  The failed cross-runtime exact-byte gate remains
`RED_UNCHANGED`.

The byte audit used 2.23 user seconds, 0.02 system seconds, 2.27 wall seconds,
and 45,916 KiB maximum RSS.  The complete hosted job occupied 291 seconds from
authoritative start to completion, with 277 seconds spent in the full-history
checkout.  This publication executes no numerical kernel, matrix exponential,
model, Torch operation, or optimizer update.

This is evidence-only.  It does not grant deterministic-backend qualification,
cross-runtime exact reproducibility, N256/N512, arbitrary histories, a fourth
release, finite-domain accuracy, full-prior or migration AD, full-network
training, asynchronous cost, production adoption, or `all_closed`.

Historical RED and UNKNOWN records remain unchanged.  Global status remains
**HOLD / NoUpdate / all_closed=false**.
