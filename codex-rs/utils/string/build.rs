include!("../../../hia/cargo_build.rs");

fn main() {
    link_native("utf8_prefix");
    link_native("metric_tag");
    link_native("markdown_location");
    link_native("ascii_json_fragment");
    link_native("truncate");
    link_native("token_budget");
    link_native("output_lines");
    link_native("uuid_find");
}
