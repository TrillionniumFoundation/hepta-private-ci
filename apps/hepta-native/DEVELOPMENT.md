# Native application development

The native application is a standalone Rust package using eframe. The shared
workspace provides the contracts, OS keyring and private-state primitives. The
application owns its local presentation, session references and platform-operation
journal; domain state stays with its existing runtime owner.

From the repository root, run:

```sh
just test -p hepta-native --manifest-path ../apps/hepta-native/Cargo.toml --cargo-profile dev-small --retries 0
just fmt
just fix -p hepta-native --manifest-path ../apps/hepta-native/Cargo.toml --profile dev-small --all-targets -- -D warnings
```

The `dev-small` profile keeps development assertions and omits debug symbols to
reduce build storage. Use the default development profile when debugging and the
release profile for release measurements.

Run the affected behavioral tests while changing a component. Shared protocol or
private-state changes also need their owning package and consumer checks. Review
updated UI snapshots when the displayed behavior changes. Ordinary development
works on any branch; Git and CI supply the actual source identity. Historical
candidate pointers and branch-specific write permits are not development inputs.

The packaged application loads a user-selected launch configuration containing a
signed endpoint manifest, trust keys and its private local-state directory. Its
transport authenticates the loopback gateway with an OS-keyring credential and
request-bound protocol-v2 MACs. An available window or successful fixture does not
prove that the production runtime is connected. Validate the configured live
owner separately, then use `--config ABSOLUTE_PATH --check-connection` before
opening the application.

`tools/package_unsigned.py` builds portable unsigned archives and checks extraction
safety. The packaging README lists platform files. Signing, installation, updates
and rollback must use the actual target configuration and retained state. Real
release observations are separate from source tests; no synthetic receipt or
cached source-status file substitutes for an installed execution.
