# Reading the original source84 logs

The acquisition manifest records 30 parts across nine complete job logs, totaling
6,134,932 bytes. Each part is stored beside its original path with the suffix
`.evidence.gz`. The original manifest and its nine supporting files retain
their original bytes. The macOS log excerpt, `MAC_NEURON_ORIGINAL_BLOCK.log`,
uses the same gzip storage as the log parts.

From the repository root, restore the registered files under their original
paths in a new directory outside the checkout.

```sh
python3 -B qa/repository-consolidation/20261115/restore_raw_evidence.py /tmp/hepta-raw-evidence
```

To verify the part boundaries, original Git identities, complete log hashes
and supporting files directly, run the original-manifest check.

```sh
python3 -B -m unittest discover -s scripts/tests -p test_source84_log_custody.py -v
```
