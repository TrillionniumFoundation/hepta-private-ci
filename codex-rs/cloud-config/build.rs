include!("../../hia/cargo_build.rs");

fn main() {
    link_native("duration_units");
    link_native("datetime_arithmetic");
}
