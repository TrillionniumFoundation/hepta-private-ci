use std::path::PathBuf;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let Some(proto_dir_arg) = std::env::args().nth(1) else {
        eprintln!("Usage: generate-proto <proto-dir>");
        std::process::exit(1);
    };

    let proto_dir = PathBuf::from(proto_dir_arg);
    let proto_file = proto_dir.join("codex.thread_config.v1.proto");

    // Preserve the narrowly scoped tonic async_trait Future lint fix
    // whenever the checked-in gRPC service trait is regenerated.
    tonic_prost_build::configure()
        .build_client(true)
        .build_server(true)
        .trait_attribute("ThreadConfigLoader", "#[allow(clippy::double_must_use)]")
        .out_dir(&proto_dir)
        .compile_protos(&[proto_file], &[proto_dir])?;

    Ok(())
}
