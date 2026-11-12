# Frozen 561d95bd source qualification

This checkpoint records only the completed full Python source QA stage at source `561d95bdf192b2631f6a762d2915d27a120d87bb`, tree `387feebbb3bc51f6d0a187137128e100ba63dea1`.

The original command was:

```text
python3 -m unittest discover -s qa/b4-no-bypass -p test_*.py -v
```

It executed **925 tests**, reported `OK`, and exited `0`. The unittest duration was 205.675 seconds; the complete recorded stage took 209.05243407100352 seconds. Both source snapshots were clean and identical: 15,494 tracked files, 234,381,882 bytes, aggregate SHA-256 `17acd96e6d244ed8e93da5cbd6785cfef083a958d2160bc5d1e08b7242f8d1b4`. The CALLERS manifest SHA-256 was `ae01152e87c0e8905631f6440988535acbc3744d82645c3979e09d23aa7d477e`, containing 1,106 boundary entries and 870 protected-file entries.

The archive preserves the original stdout/stderr, completed stage record, source snapshot, checkout/ref receipt, launch receipt, and exact driver. Its manifest and all nine input members were verified after compression. No duplicate source checkout or full source-content snapshot was created.

The authoritative full caller CLI started separately on the same frozen source. **It was still running when this QA checkpoint was created and receives no pass or failure claim here.** Its terminal record will be appended independently. The earlier af486 driver was prepared but never run; none of its results were reused.

This is an intermediate frozen source gate. It neither covers later source changes nor executes native tests. It does not establish ordinary A, Adopt, evaluated post-B NoUpdate, CURRENT/C, or whole-cold success.
