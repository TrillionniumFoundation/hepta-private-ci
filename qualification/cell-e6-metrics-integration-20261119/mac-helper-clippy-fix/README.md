# Correct the fixture helper Clippy regression

The d1d helper introduced two unwrap calls outside test functions. Actual Mac and Linux CI denied both. The new helper returns std::io::Result<tempfile::TempDir>, uses ? for canonicalize, and returns tempfile::tempdir_in directly. Six existing test functions unwrap the result. Original assertions, canonical-path validation, product source, and the other fixture remain unchanged. No allow attribute is introduced.

New source SHA256: e69d4ccd85f8a38d2720eccdaae57208a3f463951dac8bb5b833f89e89388bca. Old source SHA256: 8bc7dba30f6656fa0f0150ba2502bcd3f2f29e7f4c397c45dbb58a6d7520597f. The actual local native6 source is exact 238fc484 plus the two fixture patches, not the entire d1d or joint merge tree.

Actual native6 performed the old-to-new SHA CAS under the exclusive fixture lock, then original just fmt and fmt --check, both exit 0. Whole materialized source inventory and protected files were unchanged during validation. Original just fix then exited 101 after 1.062970125 seconds because offline Cargo lacked Inflector 0.11.4. Explicit unwrap lint and native tests were not reached. The owner exited 1 after 4.061429542 seconds. This is not a lint or native pass. All five locked Git dependency refs had already been verified, but unpacked registry directories alone did not establish usable Cargo material.

Full actual RESULT and selected original stdout/stderr are retained byte-for-byte with hashes in REMOTE_READBACK. The complete earlier native5 archive is separate. Existing failure originals are preserved; a fresh CI source must establish the remaining lint result.
