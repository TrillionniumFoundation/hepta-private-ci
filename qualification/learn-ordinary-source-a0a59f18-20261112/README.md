# Exact integrated source QA: a0a59f18

The actual complete command `python3 -m unittest discover -s qa/b4-no-bypass -p 'test_*.py' -v` completed with **914 tests passed**, exit 0. Unittest reports 216.008 seconds; the recorded stage including source observation took 219.181274573 seconds.

- Commit: `a0a59f18a63cc1ad775ae1bd079cc627a640c891`
- Tree: `f95b913e9b315966ba317bb8628621b8b7559413`
- All 15,493 tracked source entries / 234,362,498 bytes were identical before and after; aggregate SHA-256 `85511c71fbafc7e2bfd20f4b37262fc8ceb630d0917b11053a930b4d4d26a241`.
- CALLERS SHA-256: `95ca5f9122f57513d236b9ce37406dadf34b08bd4644874dc54babaa43e82c44`; this version contains 1,106 boundary rows and 870 protected-file entries.
- Original stderr: 189,679 bytes, SHA-256 `abe05dfd73843f7ea2a8e68fe9e9635812022e8a7f5e6d22b9ef3c7be0bada1c`. Original stdout is empty.

The eight original files, actual driver, complete logs and before/after observations are byte-verified in the archive. There were no failure traceback sections. Earlier failed source runs remain preserved in previous evidence commits.

No full caller CLI or Rust/native command was executed on this a0 tree in this operation. The earlier full caller PASS belongs to exact65, with its own 1,104-row source. This source-QA PASS does not establish ordinary A, Adopt, evaluated NoUpdate or cold recovery.

The separately verified source bundle contains exact a0 and its actual intervening commits, with prerequisite `32a7d4df970cbcae301068eef563bf7ed83c4e73`.
