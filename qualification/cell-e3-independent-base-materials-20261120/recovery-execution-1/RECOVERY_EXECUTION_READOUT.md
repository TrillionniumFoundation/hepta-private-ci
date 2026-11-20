# Bounded SmolLM2 range recovery: terminal evidence

**Technical state: weights incomplete (权重未齐).** The one newly authorized range-recovery owner actually ran and reached its frozen deadline. It preserved 18 complete segments and four partial segments, but did not obtain a complete weight file or establish the full upstream LFS identity. No model was loaded, run, or trained. No third download owner was started.

## Exact outcome

| Item | Retained result |
|---|---:|
| Attempted frozen segments | 22 of 95 |
| Complete segments | 18 |
| Complete-segment bytes newly received | 603,979,776 |
| Partial segments | 4 |
| Partial-segment bytes newly received and retained | 41,484,288 |
| Total new HTTP body bytes observed and written | 645,464,064 |
| Original prefix reused read-only | 255,852,544 |
| Unique retained weight positions after recovery | 901,316,608 |
| Still absent from the 3,422,777,952-byte weight | 2,521,461,344 |
| Unknown terminal segment receipts | 0 |
| Automatic retries or segment reassignments | 0 |
| New model loads / forwards / generation calls / training updates | 0 / 0 / 0 / 0 |

The prefix is reused material, not new download volume. The new output is a sparse partial file whose logical size is 3,422,777,952 bytes; that size must not be interpreted as a complete model. Its allocated bytes at termination were 901,349,376. The original partial file remains in its original location and version.

The parent owner exited 1 with `OwnerDeadline` after **895.187325511011 seconds**, inside the original 900-second wall cap. All four network workers exited and retained their own terminal receipts. The owner recorded 3.717768126 CPU seconds and its child processes recorded 14.999877 CPU seconds. Worker wall times are nested in the parent wall interval and must not be added to it. These are process measurements, not full-system energy accounting.

## Frozen source and byte gates

Model: `HuggingFaceTB/SmolLM2-1.7B-Instruct`, revision `31b70e2e869a7173562077fd711b654946d38674`. The expected complete LFS SHA256 remains `f55217be716b6a997b97b9d8d7eb6fad02e00858f5010ec24f64603c3a98a0e8`; it has **not** been verified for a complete local file.

- Original material manifest SHA256: `b26b537a35456f9ca92e4e28063ff14abf3679dfc38a20566c7ea32bd678a0b1`.
- Retained first download failure SHA256: `17a4ad6bf10b5f46c68a13ee22b93533b0f424c43803e011a909bbfe16d3f57c`.
- Previously frozen range plan v2 SHA256: `db664b8449cee85fd414982adcfb8b4c435ee348997d02cc4d998e550ab5d979`.
- New execution freeze SHA256: `4fc1811c143e14d0c43136eca4fab38143ec3b877a95fa996add18efdaf19223`.
- Executed recovery source SHA256: `eb209383a440a349f8207cbfce8416e330ebd6d456c76ab736df809c67c20bea`.
- New terminal result SHA256: `8429ccfd26c03a8266c596e7560cb728ec9bc57cf312ab3b40f7a1b549b213a2`.

The actual source and nine offline protocol checks were retained before the new owner began. Each of four workers owned fixed segment ordinals modulo four. Requests used the immutable public revision, exact nonoverlapping ranges, and no credentials or Authorization header. Real responses returned HTTP 206 with the frozen Content-Range and length. Redirects remained within public Hugging Face delivery domains; redirect/error bodies were not consumed, and temporary signed query strings were not published. Wrong ranges, a 200 response, encoded bodies, overlong bodies, and short bodies are rejected. Completed segments require stream SHA256 to match an independent read of that exact local extent.

An explicit allowance of at most one EOF-validation byte per segment was added to the conservative transport accounting; it does not increase the original four-GiB cap and cannot be written to a neighboring extent. The full planned upper bound was 3,427,266,230 bytes. At the actual terminal state, the conservative cumulative HTTP-body upper bound was **998,538,253 bytes**, including the prior observed acquisition, prior metadata, the old one-MiB unknown-read-tail reserve, and each attempted segment's full reservation. The directly observed cumulative application HTTP-body bytes were 904,756,215. Wire/TLS/header overhead and full-system cost were not measured.

The old plan-only flag is retained as a historical preparation state. A separate execution freeze records the later explicit instruction to perform the bounded recovery. No historical plan, original failure, source, or budget was silently rewritten.

## Independent terminal readback and original evidence

After the download owner was terminal, a separate read-only owner hashed the original prefix, the copied prefix, and every one of the 22 known written extents. All exact extents matched the terminal stream and local hashes; the combined unique positions total 901,316,608 bytes. This binds the bytes actually received and retained. Segment hashes do not replace the unavailable complete upstream LFS hash.

The readback took 3.777683761029 wall seconds and 3.776714075 CPU seconds, separately from the 895.187-second download window. `readback/RETAINED_EXTENTS.json` preserves every ordinal, offset, byte count and SHA256. Its SHA256 is `26dcb5a827114fbcd691558d4a27746eb2a5a141e30a595655a02a58564bab34`.

The 24,371-byte `readback/terminal-public-receipts.tar.gz` has SHA256 `ecca78131dd1ddc82bad01707d626fed8d2d86603e35f98085dbb5cf058d5326`. It retains all 90 raw receipt/source members (132,152 uncompressed bytes), including each STARTED/PROGRESS/RESULT record, worker streams and results, the actual sources and source freezes, owner intent/result, and the terminal extent readback. A separate cloud readback verified all 90 member paths, types, modes, lengths and SHA256 values with no missing or extra member. Model weight bytes are preserved on the original host and excluded from this repository archive.

## E3 scope

The already completed original T2 service experiment remains part of E3: its original twelve new calls, T1 reuse, lack of measured complementarity, maintenance results, and license-scope qualification remain unchanged. This additional material preparation adds zero to those generation and training budgets. The original E1/E2 global 56-call result is also unchanged.

SmolLM2's pinned metadata identifies an independent Llama-family base with the previously reviewed Apache-2.0 declaration; incomplete weights do not make it an executable teacher or establish complementarity. A separate Llama identity/admission profile has not been declared ready. The existing Qwen2 admission remains unchanged, and no substitute architecture was passed through that gate. No user confirmation is requested for this technical state.
