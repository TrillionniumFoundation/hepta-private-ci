# Desktop source custody — 2026-11-03 capture

This archive preserves the original desktop source snapshot as `source-custody.tar.gz`. All ten original files, including the original README and source manifest, retain their exact bytes, relative paths, and Git permission modes inside the container.

`SOURCE_MANIFEST.json` remains available beside the archive with its original eight source references. `ARCHIVE_MANIFEST.json` records the container checksum and all ten original file checksums. To inspect the capture, extract the archive into a separate empty directory; its `contexts/` paths match the original source manifest.

The container keeps these historical, incomplete worktree and patch captures outside automatic build and formatting discovery. It preserves source evidence; it does not recreate missing original commit history or certify scientific replay, tests, or production readiness. No captured source was executed during this packaging.
