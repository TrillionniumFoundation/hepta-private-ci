TaskFlow source preservation
==========================

This archive preserves exact source files, test/build scripts, patches, Git bundles, and reproduction metadata selected from five current Library packages. Each object is named by its original Git blob identity; SOURCE_MANIFEST.json maps it to original archive/member occurrences.

Verify every object with SHA-256, byte length, and Git blob SHA-1 before materializing a desired historical tree. The stored Git bundles may require the original prerequisite commits. No source is executed or placed on production paths by this preservation commit. It does not recover the separately missing October 5 JSON container or its fifteen missing embedded versions, and it does not establish complete Library synchronization.
