# Linux product compilation profile

`product-linux` inherits the original `release` profile and selects
`opt-level = "s"` and `codegen-units = 1`. Thin LTO, unwind behavior, enabled
features, source ownership, and the separate packaging strip step remain in
force. The Desktop Root companion defines the same profile in its Cargo root.

The original a059 optimized release built successfully. Independently stripped
copies measured 226,868,760 bytes for Agentd and 204,867,480 bytes for AppServer,
above the existing 128 MiB per-file product gate. Their text sections dominate;
the failure is not an unstripped debug section or one removable resource.

This profile is a measured size candidate, not a passed gate. Compile with
`cargo build --locked --offline --profile product-linux`, record the exact
clean source, compiler, command, lock and artifact hashes, and measure the
actual stripped copies. Keep failed release evidence and the original archive
bounds. Neither selecting this profile nor compilation success establishes
installed Root, model, Notes, recovery or input qualification.
