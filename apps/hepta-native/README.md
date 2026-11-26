# Hepta native shell

The desktop application connects to the local gateway, displays Fleet agents,
tracks operations, and prepares verified updates. The launcher reads the user's
platform config; `hepta-native --check-connection` verifies the configured
endpoint and returns a connection receipt without opening a window.

Gateway credentials live in the operating system keyring. The application loads
the signed endpoint and trusted public keys from the installation. Platform
effects require the configured final-use authority; enabling a UI feature does
not grant that authority.

For the Linux private-CI installation, the endpoint connection descriptor has a
maximum 24-hour validity. Install `scripts/hepta-renew-native-endpoint` as a
Root-owned `/usr/libexec/hepta/hepta-renew-native-endpoint`, install the service
and timer from `packaging/linux`, and enable
`hepta-native-endpoint-renewal.timer`. The host needs Python 3.10 or later and the
system `cryptography` package. Adjust the unit's three absolute paths when using
a different installation layout.

The maintenance tool verifies the existing signature and installed trust before
issuing a fresh bounded connection descriptor. It retains the endpoint address,
protocol, key, and keyring account, refuses revoked keys and clock rollback, and
replaces only the descriptor using a durable atomic write. It requires protected
Root-owned files and ancestors. The timer checks every six hours and writes only
when half the validity remains. It neither issues model or final-use grants nor
changes learning artifacts or their history.
