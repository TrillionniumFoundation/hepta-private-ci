# Restoring originally acquired CI logs

Run `python3 qa/repository-consolidation/20261115/restore_raw_evidence.py /path/to/new-directory` from the repository root. The destination must be a new directory outside the checkout. Each stored log is restored at its original repository-relative path. For a review of an entire collection, copy its directory to a working directory and overlay the corresponding restored files. The original manifests and acquisition metadata remain alongside the stored carriers in Git.

Run `python3 -B -m unittest discover -s scripts/tests -p test_evaluated_read_logs.py -v` to verify the source directories listed in `source-directories.json`. The test reads the original bytes of every stored log, includes every sibling file from the pinned source commit, and recomputes the Git tree identifiers of the original directories, including nested directories.
