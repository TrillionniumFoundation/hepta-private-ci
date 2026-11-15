// The shared build gate verifies the pinned HIA source and static artifact.
#[path = "../../hia/cargo_build.rs"]
mod hia_build;

fn main() {
    hia_build::link_native("seek_sequence");
    hia_build::link_native("source_file");
    hia_build::link_native("file_update");
    hia_build::link_native("parser");
    hia_build::link_native("patch_effects");
}
