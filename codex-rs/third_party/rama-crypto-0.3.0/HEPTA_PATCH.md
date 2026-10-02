# Rama crypto compatibility patch

This is the official crates.io `rama-crypto 0.3.0` source package, unchanged
except for its `time` dependency requirement: `=0.3.47` becomes `^0.3.55`.
The original package archive SHA-256 is `bdbb5a0371fe925e240d925ed5feecfc7ba5ef6843c66f66420ec6b77aa37bae`.

Matrix SDK crypto 0.19.1 requires time 0.3.55. Cargo cannot resolve that
requirement with Rama's older exact constraint within the same 0.3 family.
This patch retains Rama 0.3.0's cryptographic code, certificate validation,
features and public API. The compatible time release supplies the existing
OffsetDateTime APIs; no timestamps or authority windows are changed.

Remove the local patch when the upstream Rama crypto dependency constraint
allows the workspace's compatible time version.
