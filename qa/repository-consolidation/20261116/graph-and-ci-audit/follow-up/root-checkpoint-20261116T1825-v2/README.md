# Root checkpoint original records

The original compressed record stream and its historical manifests are preserved. Its physical carriers now use the shared [lossless storage map](../compressed-evidence-storage-v1/README.md). Run that restore command to recover the original root-records.tar.gz stream and both original logical fragments before checking the historical manifest. The restored bytes, original source commit identities, and recorded validation outcomes do not change.
