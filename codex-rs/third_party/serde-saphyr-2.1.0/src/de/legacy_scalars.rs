// Scalar-resolution helpers adapted from serde_yaml 0.9.34+deprecated src/de.rs.
// SPDX-License-Identifier: MIT OR Apache-2.0
// The scanner, alias replay and budget traversal remain serde-saphyr/granit-parser.
use super::Error;
use super::Location;
use granit_parser::ScalarStyle;
use serde_core::de::Visitor;
use std::borrow::Cow;
use std::num::ParseIntError;
#[derive(Clone, Copy)]
pub(super) enum Target {
    Any,
    Bool,
    Unsigned,
}
fn boolean(s: &str) -> Option<bool> {
    match s {
        "true" | "True" | "TRUE" => Some(true),
        "false" | "False" | "FALSE" => Some(false),
        _ => None,
    }
}
fn null(s: &str) -> bool {
    matches!(s, "null" | "Null" | "NULL" | "~")
}
fn string<'de, V: Visitor<'de>>(s: Cow<'de, str>, v: V) -> Result<V::Value, Error> {
    match s {
        Cow::Borrowed(s) => v.visit_borrowed_str(s),
        Cow::Owned(s) => v.visit_string(s),
    }
}
fn integer<'de, V: Visitor<'de>>(s: &str, v: V) -> Result<Result<V::Value, Error>, V> {
    if let Some(n) = parse_unsigned_int(s, u64::from_str_radix) {
        return Ok(v.visit_u64(n));
    }
    if let Some(n) = parse_negative_int(s, i64::from_str_radix) {
        return Ok(v.visit_i64(n));
    }
    if let Some(n) = parse_unsigned_int(s, u128::from_str_radix) {
        return Ok(v.visit_u128(n));
    }
    if let Some(n) = parse_negative_int(s, i128::from_str_radix) {
        return Ok(v.visit_i128(n));
    }
    Err(v)
}
pub(super) fn visit<'de, V: Visitor<'de>>(
    s: Cow<'de, str>,
    tag: Option<&str>,
    style: ScalarStyle,
    location: Location,
    target: Target,
    v: V,
) -> Result<V::Value, Error> {
    let error = |ty| Error::InvalidScalar { ty, location };
    match target {
        Target::Bool | Target::Unsigned => {
            let expected = match target {
                Target::Bool => "tag:yaml.org,2002:bool",
                _ => "tag:yaml.org,2002:int",
            };
            if !(matches!(style, ScalarStyle::Plain)
                || (matches!(style, ScalarStyle::Literal) && tag == Some(expected)))
            {
                return Err(error("legacy scalar style"));
            }
            return match target {
                Target::Bool => v.visit_bool(boolean(&s).ok_or_else(|| error("boolean"))?),
                Target::Unsigned => v.visit_u64(
                    parse_unsigned_int(&s, u64::from_str_radix)
                        .ok_or_else(|| error("unsigned integer"))?,
                ),
                Target::Any => unreachable!(),
            };
        }
        Target::Any => {}
    }
    match tag {
        Some("tag:yaml.org,2002:bool") => {
            return v.visit_bool(boolean(&s).ok_or_else(|| error("boolean"))?);
        }
        Some("tag:yaml.org,2002:int") => {
            return integer(&s, v).unwrap_or_else(|_| Err(error("integer")));
        }
        Some("tag:yaml.org,2002:float") => {
            return v.visit_f64(parse_f64(&s).ok_or_else(|| error("floating point"))?);
        }
        Some("tag:yaml.org,2002:null") => {
            if !null(&s) {
                return Err(error("null"));
            }
            return v.visit_unit();
        }
        Some(tag) if !tag.starts_with('!') => return string(s, v),
        _ => {}
    }
    if !matches!(style, ScalarStyle::Plain) {
        return string(s, v);
    }
    if s.is_empty() || null(&s) {
        return v.visit_unit();
    }
    if let Some(b) = boolean(&s) {
        return v.visit_bool(b);
    }
    let v = match integer(&s, v) {
        Ok(result) => return result,
        Err(v) => v,
    };
    if !digits_but_not_number(&s) {
        if let Some(n) = parse_f64(&s) {
            return v.visit_f64(n);
        }
    }
    string(s, v)
}
fn parse_unsigned_int<T>(
    scalar: &str,
    from_str_radix: fn(&str, radix: u32) -> Result<T, ParseIntError>,
) -> Option<T> {
    let unpositive = scalar.strip_prefix('+').unwrap_or(scalar);
    if let Some(rest) = unpositive.strip_prefix("0x") {
        if rest.starts_with(['+', '-']) {
            return None;
        }
        if let Ok(int) = from_str_radix(rest, 16) {
            return Some(int);
        }
    }
    if let Some(rest) = unpositive.strip_prefix("0o") {
        if rest.starts_with(['+', '-']) {
            return None;
        }
        if let Ok(int) = from_str_radix(rest, 8) {
            return Some(int);
        }
    }
    if let Some(rest) = unpositive.strip_prefix("0b") {
        if rest.starts_with(['+', '-']) {
            return None;
        }
        if let Ok(int) = from_str_radix(rest, 2) {
            return Some(int);
        }
    }
    if unpositive.starts_with(['+', '-']) {
        return None;
    }
    if digits_but_not_number(scalar) {
        return None;
    }
    from_str_radix(unpositive, 10).ok()
}

fn parse_negative_int<T>(
    scalar: &str,
    from_str_radix: fn(&str, radix: u32) -> Result<T, ParseIntError>,
) -> Option<T> {
    if let Some(rest) = scalar.strip_prefix("-0x") {
        let negative = format!("-{}", rest);
        if let Ok(int) = from_str_radix(&negative, 16) {
            return Some(int);
        }
    }
    if let Some(rest) = scalar.strip_prefix("-0o") {
        let negative = format!("-{}", rest);
        if let Ok(int) = from_str_radix(&negative, 8) {
            return Some(int);
        }
    }
    if let Some(rest) = scalar.strip_prefix("-0b") {
        let negative = format!("-{}", rest);
        if let Ok(int) = from_str_radix(&negative, 2) {
            return Some(int);
        }
    }
    if digits_but_not_number(scalar) {
        return None;
    }
    from_str_radix(scalar, 10).ok()
}

pub(crate) fn parse_f64(scalar: &str) -> Option<f64> {
    let unpositive = if let Some(unpositive) = scalar.strip_prefix('+') {
        if unpositive.starts_with(['+', '-']) {
            return None;
        }
        unpositive
    } else {
        scalar
    };
    if let ".inf" | ".Inf" | ".INF" = unpositive {
        return Some(f64::INFINITY);
    }
    if let "-.inf" | "-.Inf" | "-.INF" = scalar {
        return Some(f64::NEG_INFINITY);
    }
    if let ".nan" | ".NaN" | ".NAN" = scalar {
        return Some(f64::NAN.copysign(1.0));
    }
    if let Ok(float) = unpositive.parse::<f64>() {
        if float.is_finite() {
            return Some(float);
        }
    }
    None
}

pub(crate) fn digits_but_not_number(scalar: &str) -> bool {
    // Leading zero(s) followed by numeric characters is a string according to
    // the YAML 1.2 spec. https://yaml.org/spec/1.2/spec.html#id2761292
    let scalar = scalar.strip_prefix(['-', '+']).unwrap_or(scalar);
    scalar.len() > 1 && scalar.starts_with('0') && scalar[1..].bytes().all(|b| b.is_ascii_digit())
}
