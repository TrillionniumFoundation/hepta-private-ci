# Evidence transport correction

The original 524,280-byte parts exceeded the repository's 512,000-byte binary
blob ceiling. Revision 2 uses parts of at most 500,000 bytes: 23 runtime parts
and 7 CI-followup parts. The audit supplement is unchanged.

All assembled archive bytes, SHA-256 values, member manifests, experiment
identities, failed results and the 169 final holdout results are unchanged.
`ARTIFACTS.json` retains the exact previous manifest digest and commit. This is
a packaging repair; no training, data selection or holdout execution occurred.

Run `verify_evidence.py` in a separate output copy if the source checkout must
remain clean: the verifier assembles full archives beside their transport parts.
