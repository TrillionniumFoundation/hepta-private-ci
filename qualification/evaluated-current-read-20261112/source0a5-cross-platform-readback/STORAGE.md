# Restoring the source0a5 job logs

Run `python3 qa/repository-consolidation/20261115/restore_raw_evidence.py /path/to/new-directory` from the repository root. The destination must be a new directory outside the checkout. The restored tree contains each job part at its original repository-relative path.

Run `python3 -B -m unittest discover -s scripts/tests -p test_source0a5_log_custody.py` to verify the 50 parts, the 12 reassembled logs and the files listed in the original Git readback.
