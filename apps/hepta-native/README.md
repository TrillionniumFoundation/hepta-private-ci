# Hepta native shell

This root defines bounded native-operation intents and terminal observations.
It does not call platform APIs directly and grants no filesystem, notification,
physical-effect, promotion or release authority.

## Native packaging notices

Run `python3 apps/hepta-native/tools/prepare-notices.py <new-directory>` before
packaging the native resources. The command materializes the original
`notices/` paths and verifies all 15 notices against both resource manifests.
Some notices are compressed in the source tree; shipped notices retain the
original bytes.
