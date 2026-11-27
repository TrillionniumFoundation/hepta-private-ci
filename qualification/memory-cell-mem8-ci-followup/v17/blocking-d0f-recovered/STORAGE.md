# Reading the original MEM8 blocking run

Run the following command from the repository root. Choose a new destination
outside the checkout. The reader restores each recorded file at its original
repository-relative path.

```sh
python3 qa/repository-consolidation/20261115/restore_raw_evidence.py /tmp/mem8-originals
```

The initial recovery manifest lists 26 job logs. The terminal manifest adds
two, bringing the total to 28 logs, 64 parts and 13,751,922 original bytes.
Concatenating each job's restored parts in its recorded sequence reproduces
the full log without changing the BOM or line endings. The original JavaScript
target-table parser accepts the reassembled UTF-8 text.

To check both manifests, each part and each complete log, run:

```sh
python3 -B -m unittest discover -s scripts/tests -p test_mem8_log_custody.py
```
