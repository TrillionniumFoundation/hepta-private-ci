# Original neuroscience evidence storage

Two records introduced by the ordinary neuroscience merge exceeded the existing
512,000-byte Git blob policy. Each original is now stored as two ordered parts
of at most 500,000 bytes. No allowlist exception or size limit was added.

| Original record | Original bytes | Original SHA256 |
| --- | ---: | --- |
| `qualification/evaluated-current-read-20261112/source53-native-failure/METHOD_RESULTS.jsonl` | 568,015 | `7a7ce751812cd407c1697813e77eabf3fd8790128253056bccfd0b83a20f05fb` |
| `qualification/neuroscience-20261110/PUBLICATION_MANIFEST.json` | 531,634 | `0ed5aecb124420b76b5f08428eabe067c1d9cee6b79efa33e860d6a7dc5d0de8` |

The adjacent `.parts.json` files record original Git blob identities and exact
part order, offsets, lengths and SHA256 hashes. Concatenation was compared with
the originals in merge commit `065fa0dff71a99a9434fa9a47932715d4c2917da`.
The restored JSONL contains 1,783 original rows; the publication manifest is
the original complete JSON document. Historical manifests continue to refer
to these original filenames and hashes. Their scientific results and source
observations have not been edited.

From the repository root, restore both records to a new directory outside the
checkout. The destination's parent must already exist:

```sh
python3 qa/repository-consolidation/20261115/restore_neuro_evidence.py /tmp/hepta-neuro-originals
```

The restoration verifies every part and complete original digest before
creating the destination. It refuses to overwrite an existing destination.
The restored files retain their repository-relative paths. When checking a
historical manifest, use the restored original for each split path.

The machine-readable comparison is in `neuro-evidence-storage.json` beside this
document. This is a storage repair and did not rerun or promote an experiment.
