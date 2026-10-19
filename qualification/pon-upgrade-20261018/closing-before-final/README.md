# Retained closing observations before the final candidate

This is a byte-preserved retention increment, selected on 2026-10-18. It does not report a new native run or qualify a later source commit. Each execution keeps its original command, commit/tree, return code and scope inside the archive. The AAC v2 ordinary-upgrade run and the later PoN file-reference implementation are outside this selection.

## Verified bytes

| Item | Size | SHA-256 |
| --- | ---: | --- |
| `observations.tar.gz` | 5,364,132 bytes | `e867854e3decf94796acfa67b92bd362ce3113ee65ffb45379885d5af5b975dd` |
| `MANIFEST.json` | 234,010 bytes | `7cb641c4a32271acdeac429891a8f053e02d06849e6606648d463162e8d8b09d` |
| `hepta_closing_retention.py.received` | 32,766 bytes | `e53a2c8606ba278bc7b2a3f82fd63740b308afb0e5f3d3fb53dc9cf8ff5af92a` |

The original retention verifier streamed and verified all **223 regular members / 13,498,313 uncompressed bytes** on the native host and again after transfer on 2026-10-19. This proves archive and member integrity only. It does not turn failed or missing executions into successful tests.

## Scope and omissions

The archive includes the scoped original test/fix/format observations, real history hydration and earlier map migration records, the ordinary future run on source 544, earlier failed ordinary-upgrade runs, Supervisor preparation diagnostics, source 55 single-Start failure, original source 55 release packaging, and the rejected first AAC wrapper invocation. Its embedded selection lists every requested, selected, excluded and missing path.

Selection recorded **zero read errors** and **two missing requested files**: `/tmp/hsprobe18/debug/source-preservation.json` and `/tmp/hsprobe18/release/source-preservation.json`. These speculative filenames were absent; existing diagnostic `result.json` files retain their own actual source-preservation fields. The selection does not fabricate the missing files.

Executable products, fleet/key material, Git/Cargo trees, nested archive bodies and files larger than 4 MiB were excluded. The previous full ordinary archive is represented by its actual observed SHA-256 and size: **323,313,401 bytes**, `4ccc9cfc99b25290cae7036f0da48d216d15738be1db2c3e4eb63ef9d05eaf6a`; that archive body is not included here. The manifest's AAC source-context field is invocation navigation, not a reassignment of older test results.

## Reproduce the byte check

From any directory, use absolute paths for both retained files:

```sh
python3 /absolute/repository/qualification/pon-upgrade-20261018/closing-before-final/hepta_closing_retention.py.received verify \
  --archive /absolute/repository/qualification/pon-upgrade-20261018/closing-before-final/observations.tar.gz \
  --manifest /absolute/repository/qualification/pon-upgrade-20261018/closing-before-final/MANIFEST.json
```

The received script is retained byte-for-byte separately from working scripts. The verifier reads the compressed stream without extracting or executing its members.
