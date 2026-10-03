# Hepta native renderer

This crate owns presentation. Use the existing `hepta-native::native_host::NativeHost`
for keyring access, current Agent observations, chat intents, lifecycle controls,
and private recovery references. Runtime effects and durable domain state stay
with their existing owners.

The independent workspace pins Makepad at revision
`493d23a7630f487d29912dd73f2cbb5b639b74ca`. Follow the API in that exact
checkout; the retained [Makepad syntax reference](MAKEPAD_REFERENCE.md) contains
examples, rather than commands for this application's build or installation.

Use [the renderer guide](HEPTA_OWNER_RENDERER.md) for normal builds, resource
packaging, platform dependencies, and the original NativeShell test suite. Keep
full font and resource licenses in packaged output. Changes to presentation
need snapshot coverage and a real unprivileged window check. Connected chat and
update handoff need their own installed acceptance.

Never replay an action whose outcome is unknown. Preserve the original pending
intent and query its original receipt when that operation supports a query.
Do not give the renderer direct Fleet database access or elevated capabilities.
