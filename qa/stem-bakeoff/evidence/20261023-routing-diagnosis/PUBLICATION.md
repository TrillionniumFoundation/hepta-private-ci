# Final publication objects (revision 2)

This is a documentation correction over the same completed run-002. No experimental input, output, source pin or cost changed. Publish only the v2 chunks and the v2 receipt/checksums. The earlier ae50b2... archive is superseded publication prose, not an additional experiment.

First verify the distributed files with `sha256sum -c SHA256SUMS`.
Then reconstruct in numerical order and verify the whole archive:

```sh
cat hepta-routing-diagnosis-20261023-v2.tar.gz.part-00 hepta-routing-diagnosis-20261023-v2.tar.gz.part-01 hepta-routing-diagnosis-20261023-v2.tar.gz.part-02 hepta-routing-diagnosis-20261023-v2.tar.gz.part-03 > hepta-routing-diagnosis-20261023-v2.tar.gz
printf '%s  %s\n' '54d2a5f7189176a94d2421c30939429fbe63951fff39cabf0fef14d5ed6a4fa9' 'hepta-routing-diagnosis-20261023-v2.tar.gz' | sha256sum -c -
tar -xzf hepta-routing-diagnosis-20261023-v2.tar.gz
```

See README.md and REPRODUCE.md. Every checkpoint, original input and raw output is retained.
