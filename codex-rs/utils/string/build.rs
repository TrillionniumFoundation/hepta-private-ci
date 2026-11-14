include!("../../../hia/cargo_build.rs");

fn main() {
    link_native("utf8_prefix");
    link_native("metric_tag");
    link_native("markdown_location");
    link_native("ascii_json_fragment");
}
