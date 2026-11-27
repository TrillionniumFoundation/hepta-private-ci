# Restoring archived hosted qualification logs

Run `python3 qa/repository-consolidation/20261115/restore_raw_evidence.py /path/to/new-directory` from the repository root. The destination must be a new directory outside the checkout. It contains the original files at their historical paths. To review a complete historical acquisition, overlay these paths on a copy of the corresponding acquisition directory.

The original MEM8 Windows artifact and its standalone auditor remain available in `qualification/memory-cell-mem8-ci-followup/v17/windows-fix-v11-original/WINDOWS_SANDBOX_FIX_CEAD_ORIGINAL.tar.xz`. The extracted package supplies the original auditor's complete input directory, including `FROZEN_PLAN.json` and `ORIGINAL_ARTIFACT.zip`.

Run `python3 -B -m unittest discover -s scripts/tests -p test_evaluated_read_logs.py -v` to reconstruct the pinned Git trees of all source directories.
