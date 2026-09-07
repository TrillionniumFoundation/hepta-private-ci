# Hepta browser

This root contains an authority-free browser presentation and navigation-intent
boundary. It normalizes HTTP(S) targets, binds policy and source revisions, and
never grants network or effect authority. Servo integration is pinned separately
under `third_party/servo-patches`.

The legacy object entrypoints remain compatibility surfaces. The additive
`Local` JSON entrypoints are versioned, private-workspace internal exports for
shadow qualification, not registered module ingress or egress and not
production callers. The export is a repository convention, not JavaScript
enforcement. These entrypoints bound the encoded envelope before parsing,
require the repository's lexicographic object-key order, and reject duplicate,
missing, unknown or otherwise non-canonical fields. The local browser proposal
rejects credential and userinfo syntax, literal or encoded ASCII controls and
lone UTF-16 surrogates, preserves fragments, and caps the final
WHATWG-normalized URL at 4096 UTF-8 bytes after percent and host normalization.
It is not
`BrowserNavigationIntentV1` or a network grant. A registered effect adapter must
bind the final URL to a current lease, revocation state and VerifiedUse token
immediately before navigation.
