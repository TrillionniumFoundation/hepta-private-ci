include!("../../../hia/cargo_build.rs");

fn main() {
    link_native("citation_stream_parser");
    link_native("proposed_plan_parser");
}
