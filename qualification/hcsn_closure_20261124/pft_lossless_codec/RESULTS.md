# Lossless statistics codec: first results

The first synthetic run passed **5/5 test methods**; the first historical run passed **36/36 packets**. Every original object, canonical JSON byte sequence, float64 bit pattern and all nine declared heads were preserved.

Protocol was committed as `b537c9e791450afc3a006942eb9784ab8108a23a`; implementation and controls were frozen before execution as `0d0c6e64c36afb204c9c1d091c90727e2129e52f`. Only new modules and evidence are added; peer transport, solver and ledger are unchanged.

## Measured representations

| Parent | Packets | Canonical JSON bytes | Binary bytes | Binary / JSON |
| --- | ---: | ---: | ---: | ---: |
| n8-s17011 | 4 | 149,764 | 38,308 | 0.255789 |
| n8-s27011 | 4 | 149,755 | 38,308 | 0.255804 |
| n8-s37011 | 4 | 149,697 | 38,308 | 0.255904 |
| n32-s17011 | 4 | 1,990,019 | 439,588 | 0.220896 |
| n32-s27011 | 4 | 1,990,841 | 439,588 | 0.220805 |
| n32-s37011 | 4 | 1,988,747 | 439,588 | 0.221038 |
| n64-s17011 | 4 | 7,761,004 | 1,691,428 | 0.217939 |
| n64-s27011 | 4 | 7,773,019 | 1,691,428 | 0.217602 |
| n64-s37011 | 4 | 7,779,725 | 1,691,428 | 0.217415 |

Across all packets, **29,732,571 canonical JSON bytes became 6,507,972 binary bytes**, a **78.1116% reduction** (4.5686-fold size ratio). All 36 original Gram and `yTy` pairs were bitwise symmetric and used upper-triangle mode. This is a measured packet-size result, not an end-to-end network or training-speed result.

Measured encoding time totaled **0.9211 seconds**, decoding **1.0126 seconds**; decoding includes strict canonical re-encoding. The historical outer run took **5.4857 seconds**, including verification and writes. The synthetic outer run took **2.3309 seconds**. Each was the sole first attempt and remained below its registered 120-second cap.

## Controls and limits

The fixed controls covered all four triangular/full layouts, opposite zero signs in numerically symmetric entries, smallest finite positive subnormal, largest finite value, malformed headers and tails, stale identities, nonfinite values, wrong shapes, integer/boolean/NumPy scalar rejection and noncanonical full storage. The valid maximum metadata fixture (`d=1024`, `m=32`, `count=100000`) encoded to **7,664,887 bytes**. Changing one mirrored zero sign required full storage and was rejected because the result exceeded 8 MiB. No averaging, quantization, silent cast or mode fallback occurred.

The API is `encode_packet(packet, contract)` / `decode_packet(raw, contract)`, with magic `HPFTB001`. An enclosing transport must enforce its own complete-frame bound. Existing canonical JSON hashing is retained; this does not replace it with a new cross-language JSON convention. The codec performs no PSD, source-authentication, sample-truth, learning-quality or authority certification.

## Complete evidence

The combined `attempt-1.tar.xz` is **14,044,260 bytes**, SHA-256 `407806be2088cbdf48cd5dcdd2d3bb26baf7f64b428876cbdbf4ecec112de892`. Its 108 files include all 36 encoded packets, the exact 18 original bound input/reference files under `fixtures/`, all roundtrip results, source hashes, execution-time sources, raw logs and formatting receipt. Archive compression is only for storing evidence and is not part of the measured wire codec.

Official `just fmt` returned zero on the partial checkout; exact Ruff 0.15.13 explicitly formatted the three new qualification files. All three before/after ASTs are equal. No tests were repeated after formatting. The old numerical/scientific outcomes, training budget and final tests were not changed or rerun.

The connector has a 16 MiB request-body limit, so the unchanged archive is stored as two raw parts. `ARCHIVE_PARTS.json` binds both parts and the complete archive. Reconstruct with:

```sh
cat attempt-1.tar.xz.part01 attempt-1.tar.xz.part02 > attempt-1.tar.xz
```
