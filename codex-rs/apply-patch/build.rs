// The shared build gate verifies the pinned HIA source and static artifact.
#[path = "../../hia/cargo_build.rs"]
mod hia_build;

fn main() {
    println!(
        "cargo:rustc-check-cfg=cfg(codex_hia_unified_diff_policy, values(\"0\", \"1\", \"2\", \"3\"))"
    );
    hia_build::link_native("seek_sequence");
    hia_build::link_native("source_file");
    hia_build::link_native("file_update");
    hia_build::link_native("parser");
    hia_build::link_native("patch_effects");
    hia_build::link_native("unified_diff");
    hia_build::link_native("patch_summary");
}
