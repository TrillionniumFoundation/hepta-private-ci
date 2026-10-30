# Runtime repair evidence

REVIEW.json separates completed Linux checks from unresolved native CI checks. The frozen scientific experiments were neither changed nor repeated.

MANIFEST.json records the SHA-256 of every retained raw file and archive part. Concatenate raw.tar.gz.part000, part001, and subsequent parts in numeric order to reconstruct the gzip archive, then verify its recorded digest before extraction. Every member is a regular file under raw/. No compiled binary is included.

Failed package selection, restricted loopback, full disk, local metadata loading, and transient schema synchronization attempts remain in the archive. Earlier raw local logs lost in the workspace refresh are explicitly identified as unavailable; historical observations are not represented as new runs.
