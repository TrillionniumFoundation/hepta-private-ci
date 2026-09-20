# Codex app-server binding

The canonical plan name `codex-rs/codex-app-server` is bound to the existing
workspace package at `codex-rs/app-server`. No duplicate Cargo package or second
runtime implementation is introduced. Hepta-specific authority checks live in
`codex-rs/hepta-codex-adapter`.
