// The shared build gate verifies the pinned HIA source and static artifact.
#[path = "../../hia/cargo_build.rs"]
mod hia_build;

fn main() {
    hia_build::link_native("seek_sequence");
}
