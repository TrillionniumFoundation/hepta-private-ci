#![no_main]

use std::fs::OpenOptions;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_plasticity::DurableProposalRegistry;
use codex_hepta_plasticity::DurableTopologyProposalRegistryV1;
use codex_hepta_types::Digest32;
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    let digest = Digest32::of_bytes(data);
    let path = std::env::temp_dir().join(format!(
        "hepta-plasticity-fuzz-{}-{}",
        std::process::id(),
        digest
    ));
    let _ = std::fs::remove_file(&path);
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&path);
    let Ok(mut file) = file else {
        return;
    };
    if file.write_all(data).is_err() || file.seek(SeekFrom::Start(0)).is_err() {
        let _ = std::fs::remove_file(&path);
        return;
    }
    if let Ok(parameter_file) = file.try_clone() {
        let _ = DurableProposalRegistry::resume_unacknowledged_bootstrap(
            parameter_file,
            Digest32::of_bytes(b"fuzz-parameter-scope"),
            1,
            32,
        );
    }
    if let Ok(topology_file) = file.try_clone() {
        let _ = DurableTopologyProposalRegistryV1::resume_unacknowledged_bootstrap(
            topology_file,
            Digest32::of_bytes(b"fuzz-topology-scope"),
            1,
            32,
        );
    }
    drop(file);
    let _ = std::fs::remove_file(&path);
});
