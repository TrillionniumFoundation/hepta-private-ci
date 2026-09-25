# Platform packaging metadata

These files define deterministic **unsigned development packages** only.

- `macos/Info.plist` declares the bundle identity and high-DPI metadata.
- `windows/app.manifest` declares as-invoker execution and PerMonitorV2 DPI.
- `linux/hepta-native.desktop` declares the desktop launcher entry.
- `../tools/package_unsigned.py` assembles all three product binaries, copies
  the platform metadata, emits a deterministic ZIP, verifies every packaged
  binary against `unsigned-package-manifest.json`, extracts the ZIP into a fresh
  root and uses that extracted layout for packaged-binary smoke.

Each package receipt explicitly records that production signing, notarization
and release authorization were not observed. Package creation and packaged
binary smoke do not establish Apple notarization, Windows
Authenticode/AppUserModelID registration, Linux repository signatures,
installer trust, accessibility acceptance, promotion or release.
