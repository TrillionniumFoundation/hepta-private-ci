# Original five-lane static size failure 05

Original default Rust1.96 release build and repository strip both completed.
Host is8344952B; peer is8566248B, exceeding the unchanged8MiB file limit
by177640B. The original shape checker rejects this binary; it was
not executed. No features, profile, ELF gate or functional assertion were removed.
Source before/after bytes are identical. Both unstripped and packaged binaries
remain retained externally with exact hashes in [the original result](result.json).
Full source manifests, build/strip/readelf logs and driver are included in
[the byte manifest](publication.json). This does not qualify native five-lane
execution, physical publication or production G2.
