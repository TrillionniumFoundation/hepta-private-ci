include!("../../hia/cargo_build.rs");

fn main() {
    link_native("prefix_match");
    link_native("prefix_admission");
    link_native("policy_summary");
}
