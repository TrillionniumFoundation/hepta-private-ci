# Replay V2

Restore the parent R20 native raw evidence and exact ELF aliases as described in its TRANSPORT.md and BINARY_RESUME.md. Then, from the repository root, use fresh paths:

```sh
python -m tools.hcsn.auth_recovery_v2_r22_20261102.meter --output /tmp/hcsn-auth-v2-replay
python -m tools.hcsn.auth_recovery_v2_r22_20261102.audit --output /tmp/hcsn-auth-v2-replay
python -m tools.hcsn.auth_recovery_v2_r22_20261102.independent_v2_network --output /tmp/hcsn-auth-v2-network-replay
```

OpenSSL is required by the independent MAC checker. All fixture keys are public and unsuitable for deployment. Expected negative witness exits do not change the required zero exits of the top-level verifier/checkers. Local peer scheduling margins are part of the fixed engineering test and do not certify global or hard realtime availability.
