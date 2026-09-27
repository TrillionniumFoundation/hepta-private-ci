use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RuntimeRepresentation {
    Json,
    WireV2,
    NotAcceptable,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct Candidate {
    quality: u16,
    specificity: (u8, usize),
}

/// HTTP representation negotiation, not HPTN negotiation or peer authentication.
///
/// For each representation, its most specific matching media range determines
/// the quality (RFC 9110 section 12.5.1). In particular q=0 remains an exclusion
/// even in the presence of a less specific wildcard. Equal-specificity duplicate
/// ranges use the lower quality, independent of header order. Between supported
/// representations, prefer quality, then specificity, then the default JSON.
pub(crate) fn runtime_representation(request: &str) -> RuntimeRepresentation {
    let mut saw_accept = false;
    let mut best_json = None;
    let mut best_wire = None;
    for line in request.lines().skip(1) {
        if line.is_empty() { break; }
        let Some((name, value)) = line.split_once(':') else { continue; };
        if !name.trim().eq_ignore_ascii_case("accept") { continue; }
        saw_accept = true;
        for raw in split_quoted(value, ',') {
            if raw.trim().is_empty() { continue; }
            let Some(range) = parse_media_range(raw) else {
                return RuntimeRepresentation::NotAcceptable;
            };
            if let Some(candidate) = matching_candidate(&range, "json", &[("charset", "utf-8")]) {
                update_best(&mut best_json, candidate);
            }
            if let Some(candidate) = matching_candidate(&range, "x-hepta-wire", &[("version", "2")]) {
                update_best(&mut best_wire, candidate);
            }
        }
    }
    if !saw_accept { return RuntimeRepresentation::Json; }
    let json = best_json.filter(|c: &Candidate| c.quality > 0);
    let wire = best_wire.filter(|c: &Candidate| c.quality > 0);
    match (wire, json) {
        (Some(wire), Some(json)) if (wire.quality, wire.specificity) > (json.quality, json.specificity) => RuntimeRepresentation::WireV2,
        (Some(_), Some(_)) | (None, Some(_)) => RuntimeRepresentation::Json,
        (Some(_), None) => RuntimeRepresentation::WireV2,
        (None, None) => RuntimeRepresentation::NotAcceptable,
    }
}

fn matching_candidate(range: &MediaRange, subtype: &str, parameters: &[(&str, &str)]) -> Option<Candidate> {
    let specificity = match (range.kind.as_str(), range.subtype.as_str()) {
        ("*", "*") => 0,
        ("application", "*") => 1,
        ("application", observed) if observed == subtype => 2,
        _ => return None,
    };
    for (name, value) in &range.parameters {
        let (_, expected) = parameters.iter().find(|(expected_name, _)| name == expected_name)?;
        let matches = if name == "charset" { value.eq_ignore_ascii_case(expected) } else { value == expected };
        if !matches { return None; }
    }
    Some(Candidate { quality: range.quality, specificity: (specificity, range.parameters.len()) })
}

fn update_best(best: &mut Option<Candidate>, candidate: Candidate) {
    match best {
        None => *best = Some(candidate),
        Some(current) if candidate.specificity > current.specificity => *current = candidate,
        Some(current) if candidate.specificity == current.specificity => {
            current.quality = current.quality.min(candidate.quality);
        }
        Some(_) => {}
    }
}

#[derive(Debug)]
struct MediaRange {
    kind: String,
    subtype: String,
    parameters: BTreeMap<String, String>,
    quality: u16,
}

fn parse_media_range(raw: &str) -> Option<MediaRange> {
    let mut fields = split_quoted(raw, ';').into_iter();
    let media_type = fields.next()?.trim().to_ascii_lowercase();
    let (kind, subtype) = media_type.split_once('/')?;
    if !valid_token(kind) || !valid_token(subtype) || (kind == "*" && subtype != "*") {
        return None;
    }
    let mut parameters = BTreeMap::new();
    let mut quality = None;
    for field in fields {
        let (name, raw_value) = field.trim().split_once('=')?;
        let name = name.trim().to_ascii_lowercase();
        if !valid_token(&name) { return None; }
        if name == "q" {
            if quality.replace(parse_quality(raw_value.trim())?).is_some() { return None; }
        } else {
            let value = parameter_value(raw_value.trim())?;
            if parameters.insert(name, value).is_some() { return None; }
        }
    }
    Some(MediaRange { kind: kind.to_string(), subtype: subtype.to_string(), parameters, quality: quality.unwrap_or(1000) })
}

fn valid_token(value: &str) -> bool {
    !value.is_empty() && value.bytes().all(|byte| byte.is_ascii_alphanumeric() || matches!(byte,
        b'!' | b'#' | b'$' | b'%' | b'&' | b'\'' | b'*' | b'+' | b'-' | b'.' | b'^' | b'_' | b'`' | b'|' | b'~'))
}

fn parameter_value(value: &str) -> Option<String> {
    if !value.starts_with('"') { return valid_token(value).then(|| value.to_string()); }
    let inner = value.strip_prefix('"')?.strip_suffix('"')?;
    let mut output = String::new();
    let mut escaped = false;
    for character in inner.chars() {
        if escaped {
            if character != '\t' && (character < ' ' || character == '\u{7f}') { return None; }
            output.push(character);
            escaped = false;
        } else if character == '\\' {
            escaped = true;
        } else if character == '"' || (character != '\t' && (character < ' ' || character == '\u{7f}')) {
            return None;
        } else { output.push(character); }
    }
    (!escaped).then_some(output)
}

fn parse_quality(value: &str) -> Option<u16> {
    let (whole, fraction) = value.split_once('.').unwrap_or((value, ""));
    if fraction.len() > 3 || !fraction.bytes().all(|byte| byte.is_ascii_digit()) { return None; }
    match whole {
        "0" => {
            let mut quality = 0_u16;
            for (index, byte) in fraction.bytes().enumerate() { quality += u16::from(byte - b'0') * [100, 10, 1][index]; }
            Some(quality)
        }
        "1" if fraction.bytes().all(|byte| byte == b'0') => Some(1000),
        _ => None,
    }
}

fn split_quoted(value: &str, delimiter: char) -> Vec<&str> {
    let mut fields = Vec::new();
    let mut start = 0;
    let mut quoted = false;
    let mut escaped = false;
    for (index, character) in value.char_indices() {
        if escaped { escaped = false; continue; }
        match character {
            '\\' if quoted => escaped = true,
            '"' => quoted = !quoted,
            current if current == delimiter && !quoted => {
                fields.push(&value[start..index]);
                start = index + current.len_utf8();
            }
            _ => {}
        }
    }
    fields.push(&value[start..]);
    fields
}

#[cfg(test)]
mod tests {
    use super::*;
    fn choose(accept: &str) -> RuntimeRepresentation {
        runtime_representation(&format!("GET /api/hepta/runtime HTTP/1.1\r\nHost: localhost\r\n{accept}\r\n\r\n"))
    }
    #[test]
    fn absent_accept_defaults_to_json() {
        assert_eq!(runtime_representation("GET / HTTP/1.1\r\nHost: localhost\r\n\r\n"), RuntimeRepresentation::Json);
    }
    #[test]
    fn wire_parameters_are_order_and_quote_insensitive() {
        for accept in ["Accept: application/x-hepta-wire; version=2", "Accept: Application/X-Hepta-Wire;VERSION=\"2\"", "Accept: application/x-hepta-wire ; q = 0.8 ; version = 2"] {
            assert_eq!(choose(accept), RuntimeRepresentation::WireV2, "{accept}");
        }
    }
    #[test]
    fn quality_and_specificity_choose_the_best_supported_representation() {
        assert_eq!(choose("Accept: application/x-hepta-wire;version=2;q=0.4, application/json;q=0.9"), RuntimeRepresentation::Json);
        assert_eq!(choose("Accept: */*;q=0.5, application/x-hepta-wire;version=2;q=0.5"), RuntimeRepresentation::WireV2);
    }
    #[test]
    fn unsupported_wire_can_fall_back_to_json() {
        assert_eq!(choose("Accept: application/x-hepta-wire;version=99, application/json;q=0.5"), RuntimeRepresentation::Json);
        assert_eq!(choose("Accept: application/*"), RuntimeRepresentation::Json);
    }
    #[test]
    fn explicit_exclusion_or_unrelated_ranges_fail_closed() {
        for accept in ["Accept: application/x-hepta-wire;version=2;q=0", "Accept: text/plain", "Accept: application/x-hepta-wire;version=99", "Accept: application/json;q=bogus", "Accept: application/x-hepta-wire;version=2;version=2"] {
            assert_eq!(choose(accept), RuntimeRepresentation::NotAcceptable, "{accept}");
        }
    }
    #[test]
    fn multiple_accept_fields_are_combined() {
        assert_eq!(choose("Accept: application/json;q=0.3\r\nAccept: application/x-hepta-wire;version=2;q=0.7"), RuntimeRepresentation::WireV2);
    }
    #[test]
    fn quality_parser_accepts_only_rfc_bounds() {
        for (input, expected) in [("0", Some(0)), ("0.001", Some(1)), ("0.999", Some(999)), ("1.000", Some(1000)), ("1.001", None), ("0.0000", None), (".5", None)] {
            assert_eq!(parse_quality(input), expected);
        }
    }
    #[test]
    fn wildcard_cannot_resurrect_an_explicit_exclusion() {
        for accept in ["Accept: application/json;q=0, application/x-hepta-wire;q=0, */*;q=1", "Accept: */*;q=1\r\nAccept: application/x-hepta-wire;q=0\r\nAccept: application/json;q=0"] {
            assert_eq!(choose(accept), RuntimeRepresentation::NotAcceptable);
        }
        assert_eq!(choose("Accept: application/json;q=0, */*;q=1"), RuntimeRepresentation::WireV2);
    }
    #[test]
    fn parameter_specificity_controls_quality_before_cross_representation_choice() {
        assert_eq!(choose("Accept: application/x-hepta-wire;q=1, application/x-hepta-wire;version=2;q=0, application/json;q=0.3"), RuntimeRepresentation::Json);
        assert_eq!(choose("Accept: */*;q=1, application/json;q=0.1, application/x-hepta-wire;version=2;q=0.2"), RuntimeRepresentation::WireV2);
    }
    #[test]
    fn unknown_parameters_do_not_match_supported_representations() {
        assert_eq!(choose("Accept: application/x-hepta-wire;foo=bar;version=2"), RuntimeRepresentation::NotAcceptable);
        assert_eq!(choose("Accept: application/json;charset=UTF-8"), RuntimeRepresentation::Json);
        assert_eq!(choose("Accept: application/json;charset=latin1"), RuntimeRepresentation::NotAcceptable);
    }
    #[test]
    fn conflicting_duplicate_ranges_are_header_order_independent() {
        for accept in ["Accept: application/json;q=0, application/json;q=1", "Accept: application/json;q=1\r\nAccept: application/json;q=0"] {
            assert_eq!(choose(accept), RuntimeRepresentation::NotAcceptable);
        }
    }
    #[test]
    fn malformed_quoted_or_duplicate_parameters_reject() {
        for accept in ["Accept: application/json;q=\"1\"", "Accept: application/json;foo", "Accept: application/x-hepta-wire;version=\"2", "Accept: application/json;foo=a;FOO=b", "Accept: application/json;q=1;q=0"] {
            assert_eq!(choose(accept), RuntimeRepresentation::NotAcceptable, "{accept}");
        }
    }
    #[test]
    fn quoted_pair_decoding_does_not_split_inside_values() {
        assert_eq!(parameter_value("\"\\2\""), Some("2".to_string()));
        assert_eq!(split_quoted("a;foo=\"b,c\",d", ','), vec!["a;foo=\"b,c\"", "d"]);
        assert_eq!(choose("Accept: application/x-hepta-wire;version=\"\\2\""), RuntimeRepresentation::WireV2);
    }
}
