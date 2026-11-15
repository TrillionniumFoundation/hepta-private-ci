include!("../../../hia/cargo_build.rs");

fn main() {
    link_native("template_parser");
    link_native("template_render");
    link_native("template_index");
}
