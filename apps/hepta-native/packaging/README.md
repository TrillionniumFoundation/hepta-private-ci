# Platform packaging metadata

These files define development packaging metadata only.

- `macos/Info.plist` declares the bundle identity and high-DPI application metadata.
- `windows/app.manifest` declares as-invoker execution and PerMonitorV2 DPI behavior.
- `linux/hepta-native.desktop` declares the desktop launcher entry.

They do not establish code signing, Apple notarization, Windows Authenticode/AppUserModelID registration, Linux repository signatures, installer trust, promotion, or release. CI-generated archives remain explicitly unsigned.
