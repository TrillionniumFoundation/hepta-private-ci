# Platform packaging metadata

These files define deterministic **unsigned development packages** only.

- `macos/Info.plist` declares the bundle identity and high-DPI metadata.
- `windows/app.manifest` declares as-invoker execution and PerMonitorV2 DPI.
- The packaged Rust executable provides the explicit Windows installation command
  `hepta-native.exe --register-notification-identity`. It creates the per-user
  Start Menu shortcut for that exact executable, commits `Trillionnium.Hepta.Native`
  through the native SDK `IPropertyStore`, and verifies the stored shortcut target
  and identity before atomically publishing the notification marker.
- `linux/hepta-native.desktop` declares the desktop launcher entry. Linux file
  selection uses XDG Desktop Portal through Rust D-Bus calls. The former Zenity
  compatibility option now returns a clear unsupported-backend error; configure
  `HEPTA_NATIVE_PICKER_BACKEND=portal` or leave it unset.
- `../tools/package_unsigned.py` assembles all three product binaries, copies
  the platform metadata, emits a deterministic
  ZIP, verifies every packaged file against `unsigned-package-manifest.json`,
  extracts the ZIP into a fresh root and uses that extracted layout for
  packaged-binary smoke.

The v3 package manifest records the exact two-element Rust registrar command on
Windows and null elsewhere. It neither installs nor runs the former PowerShell
registrar; that source remains a historical compatibility artifact. Package
creation and application startup never register an identity automatically.
On a Windows qualification host, an explicitly approved installation step must
run the command from its intended installed location, verify the shortcut
AppUserModelID and target, launch that exact binary, exercise a WinRT toast, and
retain logs and digests. Declaring the command does not prove registration.

Each package receipt explicitly records that production signing, notarization
and release authorization were not observed. Package creation and packaged
binary smoke do not establish Apple notarization, Windows Authenticode or
AppUserModelID registration, Linux repository signatures, installer trust,
accessibility acceptance, promotion or release.
