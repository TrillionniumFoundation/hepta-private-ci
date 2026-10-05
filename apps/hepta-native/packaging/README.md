# Platform packaging metadata

These files define deterministic **unsigned development packages** only.

- `macos/Info.plist` declares the bundle identity and high-DPI metadata.
- `windows/app.manifest` declares as-invoker execution and PerMonitorV2 DPI.
- `windows/Register-HeptaNativeIdentity.ps1` creates the per-user Start Menu
  shortcut, commits `Trillionnium.Hepta.Native` through `IPropertyStore`, then
  publishes the local identity marker consumed by the WinRT notification adapter.
- `linux/hepta-native.desktop` declares the desktop launcher entry. Linux file
  selection is XDG Desktop Portal-first; Zenity is an explicit compatibility
  backend selected with `HEPTA_NATIVE_PICKER_BACKEND=zenity`.
- `../tools/package_unsigned.py` assembles all three product binaries, copies
  the platform metadata and Windows identity registrar, emits a deterministic
  ZIP, verifies every packaged file against `unsigned-package-manifest.json`,
  extracts the ZIP into a fresh root and uses that extracted layout for
  packaged-binary smoke.

The Windows identity script is package material, not evidence that registration
was executed successfully. Physical Windows qualification must run the script,
verify the shortcut AppUserModelID, launch the exact packaged binary, exercise a
WinRT toast, and retain the resulting logs and digests.

Each package receipt explicitly records that production signing, notarization
and release authorization were not observed. Package creation and packaged
binary smoke do not establish Apple notarization, Windows Authenticode or
AppUserModelID registration, Linux repository signatures, installer trust,
accessibility acceptance, promotion or release.
