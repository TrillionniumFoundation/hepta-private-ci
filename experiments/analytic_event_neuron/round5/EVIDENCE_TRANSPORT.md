# New evidence envelopes

Round5 stores new raw scientific artifacts in versioned UTF-8 envelopes when
the available Git connector cannot carry binary bodies. These are standard
base64 chunks of a deterministic gzip/tar archive. They are not Git LFS pointers,
replacement historical evidence, or an alternative scientific data format.

Each `evidence/envelopes/<name>/MANIFEST.json` binds the decoded archive, each
encoded and decoded chunk, and every original member by byte count and SHA256.
The member paths are relative to the declared source directory. Model, data,
source, registration and freeze identities remain the scientific authority;
an archive transport receipt does not establish a statistical result.

After checking out this research commit, restore any envelope into a new
directory with the Python standard library alone:

```bash
python -m experiments.analytic_event_neuron.round5.evidence_io restore \
  experiments/analytic_event_neuron/round5/evidence/envelopes/ENVELOPE_NAME \
  /tmp/NEW_EMPTY_DESTINATION
```

The command refuses to overwrite an existing destination. Before writing any
member it checks the complete chunk inventory, strict base64 encoding, archive
digest, regular-file member inventory, normalized paths, sizes and member
digests. No symlinks, external download or arbitrary archive extraction are used.
The emitted receipt reports the original bytes actually checked.

The completed pre-review development smoke remains immutable. Its five then-new
selection sources are preserved in `evidence/source_history/smoke_001` and match
its preparation snapshot. The inherited 102 scientific dependencies are the
unchanged Round4 frozen files. Subsequent review fixes have their own source
identities and cannot retroactively rewrite that development attempt.

The 38 historical Round4 binary archive files still present in the remote Git
tree are a separate inventory. Their identities were recovered from the tree;
their bytes were not recovered into this workspace. No Round5 envelope contains
fabricated replacements for them or for the unpublished final Round4 artifacts.
