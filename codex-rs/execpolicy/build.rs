include!("../../hia/cargo_build.rs");

fn main() {
    link_native("prefix_match");
    link_native("prefix_admission");
    link_native("policy_summary");
    link_native("network_domains");
    link_native("allowed_prefixes");
    link_native("command_dispatch");
    link_native("network_host");
}
