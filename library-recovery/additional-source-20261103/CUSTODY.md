# Current source custody

The historical sources and their original controls are preserved as data in 1 bounded source-custody volumes. SOURCE_VOLUMES.json maps all 92 original repository files (871730 bytes) to their unchanged member paths, Git modes, Git blob IDs and SHA256 hashes at commit c2130629037b342e6e48154867b65acc8fc82434.

The maintained reader verifies the registered manifest, every compressed and expanded volume, every original member, and the visible original manifests and notices. It never extracts, imports or executes historical sources. From the repository root:

```sh
python3 -B scripts/verify_source_custody_volumes.py library-recovery/additional-source-20261103
```

Original README and reproduction commands remain historical records. Their source paths now refer to members of these volumes; reproducing a historical program requires its original context and a separate qualification. Original versions of maintenance readers are also retained inside the volumes. Existing maintained byte verifiers continue to check the original source manifests; optional notebook extraction checks remain available.

Original source counts, unresolved inputs, negative results, licenses and admission limits are unchanged. Byte custody is not a model experiment, scientific acceptance, native compatibility result, deployment permit or proof of complete branch integration.
