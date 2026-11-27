use paste::expr;
use paste::item;
use paste::paste;

// V8's typed-array and cppgc wrappers paste names inside declarative macros.
macro_rules! typed_array {
    ($name:ident, $element:ty) => {
        paste! {
            struct [<$name Array>]($element);

            impl [<$name Array>] {
                fn [<as_ $name:snake>](&self) -> $element {
                    self.0
                }
            }
        }
    };
}

typed_array!(Uint8, u8);
typed_array!(BigInt64, i64);

// Starlark reexports item through another crate before invoking it.
mod starlark_style {
    pub use paste::item;
}

starlark_style::item! {
    const [<STARLARK _ MODULE>]: &str = "available";
}

item! {
    #[doc = "getter for " "field"]
    fn [<get_ value>]() -> u32 {
        42
    }
}

#[test]
fn v8_style_names_and_integer_suffixes_compile() {
    assert_eq!(Uint8Array(255).as_uint8(), 255);
    assert_eq!(BigInt64Array(-1).as_big_int64(), -1);
}

#[test]
fn starlark_style_cross_crate_reexport_expands() {
    assert_eq!(STARLARK_MODULE, "available");
}

#[test]
fn item_and_expr_entry_points_preserve_expansion() {
    let value = 7;
    assert_eq!(get_value(), 42);
    assert_eq!(expr! { [<val ue>] + 1 }, 8);
}

#[test]
fn case_conversion_raw_identifiers_and_lifetimes_expand() {
    paste! {
        struct [<http_client:camel>]<[<'input>]> {
            r#type: &[<'input>] str,
        }
        const [<lower:upper>]: &str = "case";
    }
    let client = HttpClient { r#type: LOWER };
    assert_eq!(client.r#type, "case");
}
