# Original five-lane static ELF shape failure

Frozen b182ce0c7 built and packaged successfully using default features, the
original Rust1.96 release profile and original static GNU flags. Cargo's build
reported 39m55s; the wrapper took 2447.716s. Full tracked source bytes before and
after were identical. Original release symbol archiving and stripping succeeded.

The packaged Host is 8344952 bytes and passes the original 8388608-byte gate.
The real two-consumer qualification peer is 8759816 bytes, exceeding that gate
by 371208 bytes. The original checker rejected it and the durable job exited1.
No oversized peer was executed, no limit was raised and no functionality or
feature was disabled. Its successful build is not native qualification.

Original build/packaging logs, readelf output, command/environment/source hashes
and both packaged/unstripped identities are retained here. The actual original
executables and symbol archives remain outside Git. Native five-lane consumers,
full Prepare/Commit material publication and persistent G2 remain open.

See [the complete original-byte manifest](publication.json).
