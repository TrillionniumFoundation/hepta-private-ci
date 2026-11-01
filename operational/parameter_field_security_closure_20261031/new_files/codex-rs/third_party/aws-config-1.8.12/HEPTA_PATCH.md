# AWS config 1.8.12: maintained P-256 arithmetic

Published archive SHA-256:
`96571e6996817bf3d58f6b569e4b9fd2e9d2fcf9f7424eed07b2ce9bb87535e5`.
The original Apache license and all AWS credential provider features remain.

The optional `credentials-login` implementation advances `p256` from 0.13.2
to 0.14.0 and its RNG from rand 0.8.5 to 0.10.3. This reaches the maintained
elliptic-curve 0.14 / crypto-bigint 0.7 line, where RUSTSEC-2026-0387 is fixed
in crypto-bigint 0.7.6 and later. The candidate lock must contain the reviewed
0.7.10 release and ctutils 0.4.7; the policy check remains mandatory.

The small DPoP adaptation uses the renamed SEC1-point method and a system-seeded
cryptographic RNG. It preserves randomized ES256 signatures; it does not switch
off login support or replace cryptography with a local implementation. Entropy
and signing failures propagate as LoginTokenError. Existing coordinate, payload,
valid-key and invalid-key tests remain; a regression verifies the raw 64-byte
DPoP signature and rejects a modified payload.

The workspace pins 1.8.12 so a broad AWS update cannot silently bypass this
local compatibility patch. Remove the patch after a compatible maintained AWS
release adopts the fixed P-256 dependency and passes the same tests.

