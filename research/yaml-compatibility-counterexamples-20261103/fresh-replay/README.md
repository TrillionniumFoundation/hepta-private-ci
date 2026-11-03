# Actual fresh replay after environment recovery

This is a new execution, with all source/command/output bindings retained; it is not a reconstruction of missing historical logs. It confirms the same failures and does not qualify a migration.

Official serde-saphyr 2.1.0 and the fork with its option off each produced 1,574 observations with 472 differences. Their full matrix stdout is byte-identical (SHA256 42d608b2392a9836089b84350068274d81cfabc5a396cb4f41372e0633bb642a). The enabled local policy still has 312 differences. All three expanded consumer harness runs exit 101 (13 passed, 1 failed); the 28 additional command/skill examples retain 22/22/20 differences. Seven narrow policy controls pass.

RECEIPT.json contains the actual Rust 1.95 compiler argv, compiler hash, input rlib/executable hashes, all source hashes, exit codes and stdout/stderr hashes. Both source and shared input checks remained unchanged. SOURCE_MAPPING.json resolves each source input to an exact archived source object or the checksum-verified upstream package plus the exact three-file patch. Repeated source objects are stored once. Some recovered source comments describe their historical reconstruction; this receipt specifically binds their subsequent new execution.

complete-output.tar.gz contains all 42 complete stdout/stderr streams. OUTPUTS.json gives every member's byte length and SHA256. This small deterministic archive preserves complete negative evidence without publishing binaries or caches. The isolated dependency support manifest and lock are retained; no production dependency or lockfile was changed.

The replay orchestration is ../replay_bound_probes.py. It accepts explicit compiler, dependency rlib directory and isolated replay/source paths. Dependency build setup is recorded in build-support. The original command environment used CARGO_INCREMENTAL=0 and one Cargo job. Full native consumer builds, workspace feature resolution and advisory closure remain outside this replay.
