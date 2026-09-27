#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RuntimeRepresentation {
    Json,
    WireV2,
    NotAcceptable,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct Candidate {
    specificity: u8,
    quality: u16,
}

/// Select the response representation from all HTTP Accept fields.
///
/// This is HTTP representation negotiation only. It does not establish an
/// HPTN protocol session and it does not authenticate a peer. For each representation the most
/// specific matching range determines quality (RFC 9110, section 12.5.1).
/// Explicit q=0 exclusions therefore override wildcard ranges. Parameter names are case-insensitive,
/// quoted version values are accepted, q=0 is an explicit exclusion, and an
/// unsupported wire version may fall back to an independently acceptable JSON
/// range.
pub(crate) fn runtime_representation(request: &str) -> RuntimeRepresentation {
    let mut saw_accept = false;
    let mut best_json = None;
    let mut best_wire = None;

    for line in request.lines().skip(1) {
        if line.is_empty() {
            break;
        }
        let Some((name, value)) = line.split_once(':') else {
            continue;
        };
        if !name.trim().eq_ignore_ascii_case("accept") {
            continue;
        }
        saw_accept = true;
        for raw_range in split_quoted(value, ',') {
            let Some(range) = parse_media_range(raw_range) else {
                continue;
            };
            if range.unsupported_parameters {
                continue;
            }
            match range.media_type.as_str() {
                "application/x-hepta-wire"
                    if range.version.as_deref() == Some("2") && range.charset.is_none() =>
                {
                    update_best(
                        &mut best_wire,
                        Candidate {
                            quality: range.quality,
                            specificity: 3,
                        },
                    );
                }
                "application/json" if range.version.is_none() => {
                    update_best(
                        &mut best_json,
                        Candidate {
                            quality: range.quality,
                            specificity: if range.charset.is_some() { 4 } else { 3 },
                        },
                    );
                }
                "application/*" if range.version.is_none() && range.charset.is_none() => {
                    update_best(
                        &mut best_json,
                        Candidate {
                            quality: range.quality,
                            specificity: 2,
                        },
                    );
                }
                "*/*" if range.version.is_none() && range.charset.is_none() => {
                    update_best(
                        &mut best_json,
                        Candidate {
                            quality: range.quality,
                            specificity: 1,
                        },
                    );
                }
                _ => {}
            }
        }
    }

    if !saw_accept {
        return RuntimeRepresentation::Json;
    }
    let best_wire = best_wire.filter(|candidate| candidate.quality != 0);
    let best_json = best_json.filter(|candidate| candidate.quality != 0);
    match (best_wire, best_json) {
        (Some(wire), Some(json))
            if (wire.quality, wire.specificity) >= (json.quality, json.specificity) =>
        {
            RuntimeRepresentation::WireV2
        }
        (Some(_), Some(_)) => RuntimeRepresentation::Json,
        (Some(_), None) => RuntimeRepresentation::WireV2,
        (None, Some(_)) => RuntimeRepresentation::Json,
        (None, None) => RuntimeRepresentation::NotAcceptable,
    }
}

fn update_best(best: &mut Option<Candidate>, candidate: Candidate) {
    if best.is_none_or(|current| candidate > current) {
        *best = Some(candidate);
    }
}

#[derive(Debug)]
struct MediaRange {
    media_type: String,
    version: Option<String>,
    charset: Option<String>,
    unsupported_parameters: bool,
    quality: u16,
}

fn parse_media_range(raw: &str) -> Option<MediaRange> {
    let mut fields = split_quoted(raw, ';').into_iter();
    let media_type = fields.next()?.trim().to_ascii_lowercase();
    let (kind, subtype) = media_type.split_once('/')?;
    if !valid_token_or_star(kind)
        || !valid_token_or_star(subtype)
        || (kind == "*" && subtype != "*")
    {
        return None;
    }

    let mut version = None;
    let mut charset = None;
    let mut unsupported_parameters = false;
    let mut parameters = std::collections::BTreeSet::new();
    let mut quality = None;
    for field in fields {
        let field = field.trim();
        if field.is_empty() {
            continue;
        }
        let (name, raw_value) = field.split_once('=')?;
        let name = name.trim().to_ascii_lowercase();
        if !valid_token(&name) {
            return None;
        }
        if !parameters.insert(name.clone()) {
            return None;
        }
        let value = unquote(raw_value.trim())?;
        match name.as_str() {
            "version" => {
                if version.replace(value.to_string()).is_some() {
                    return None;
                }
            }
            "q" => {
                if quality.replace(parse_quality(value)?).is_some() {
                    return None;
                }
            }
            "charset" => {
                if !value.eq_ignore_ascii_case("utf-8") {
                    unsupported_parameters = true;
                }
                charset = Some(value.to_string());
            }
            _ => unsupported_parameters = true,
        }
    }

    Some(MediaRange {
        media_type,
        version,
        charset,
        unsupported_parameters,
        quality: quality.unwrap_or(1000),
    })
}

fn valid_token_or_star(value: &str) -> bool {
    value == "*" || valid_token(value)
}

fn valid_token(value: &str) -> bool {
    !value.is_empty()
        && value.bytes().all(|byte| {
            byte.is_ascii_alphanumeric()
                || matches!(
                    byte,
                    b'!' | b'#'
                        | b'$'
                        | b'%'
                        | b'&'
                        | b'\''
                        | b'*'
                        | b'+'
                        | b'-'
                        | b'.'
                        | b'^'
                        | b'_'
                        | b'`'
                        | b'|'
                        | b'~'
                )
        })
}

fn unquote(value: &str) -> Option<&str> {
    if let Some(inner) = value.strip_prefix('"').and_then(|v| v.strip_suffix('"')) {
        if inner.contains('"') || inner.contains('\\') {
            return None;
        }
        Some(inner)
    } else if value.contains('"') {
        None
    } else {
        Some(value)
    }
}

fn parse_quality(value: &str) -> Option<u16> {
    let (whole, fraction) = value.split_once('.').unwrap_or((value, ""));
    if fraction.len() > 3 || !fraction.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    match whole {
        "0" => {
            let mut quality = 0_u16;
            for (index, byte) in fraction.bytes().enumerate() {
                quality += u16::from(byte - b'0') * [100, 10, 1][index];
            }
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
        if escaped {
            escaped = false;
            continue;
        }
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

    fn request(accept: &str) -> String {
        format!("GET /api/hepta/runtime HTTP/1.1\r\nHost: localhost\r\n{accept}\r\n")
    }

    #[test]
    fn absent_accept_defaults_to_json() {
        assert_eq!(
            runtime_representation("GET / HTTP/1.1\r\nHost: localhost\r\n\r\n"),
            RuntimeRepresentation::Json
        );
    }

    #[test]
    fn wire_parameters_are_order_and_quote_insensitive() {
        for accept in [
            "Accept: application/x-hepta-wire; version=2",
            "Accept: Application/X-Hepta-Wire;VERSION=\"2\"",
            "Accept: application/x-hepta-wire ; q = 0.8 ; version = 2",
        ] {
            assert_eq!(
                runtime_representation(&request(accept)),
                RuntimeRepresentation::WireV2,
                "{accept}"
            );
        }
    }

    #[test]
    fn quality_and_specificity_choose_the_best_supported_representation() {
        assert_eq!(
            runtime_representation(&request(
                "Accept: application/x-hepta-wire;version=2;q=0.4, application/json;q=0.9"
            )),
            RuntimeRepresentation::Json
        );
        assert_eq!(
            runtime_representation(&request(
                "Accept: */*;q=0.5, application/x-hepta-wire;version=2;q=0.5"
            )),
            RuntimeRepresentation::WireV2
        );
    }

    #[test]
    fn unsupported_wire_can_fall_back_to_json() {
        assert_eq!(
            runtime_representation(&request(
                "Accept: application/x-hepta-wire;version=99, application/json;q=0.5"
            )),
            RuntimeRepresentation::Json
        );
        assert_eq!(
            runtime_representation(&request("Accept: application/*")),
            RuntimeRepresentation::Json
        );
    }

    #[test]
    fn explicit_exclusion_or_unrelated_ranges_fail_closed() {
        for accept in [
            "Accept: application/x-hepta-wire;version=2;q=0",
            "Accept: text/plain, application/x-hepta-wire;foo=bar;version=2",
            "Accept: application/json;foo=bar",
            "Accept: application/json;charset=latin1",
            "Accept: application/json;q=0, */*;q=1",
            "Accept: application/json;q=0, application/*;q=1",
            "Accept: text/plain",
            "Accept: application/x-hepta-wire;version=99",
            "Accept: application/json;q=bogus",
            "Accept: application/x-hepta-wire;version=2;version=2",
        ] {
            assert_eq!(
                runtime_representation(&request(accept)),
                RuntimeRepresentation::NotAcceptable,
                "{accept}"
            );
        }
    }

    #[test]
    fn multiple_accept_fields_are_combined() {
        let request = "GET /api/hepta/runtime HTTP/1.1\r\n\
Host: localhost\r\n\
Accept: application/json;q=0.3\r\n\
Accept: application/x-hepta-wire; version=2; q=0.7\r\n\r\n";
        assert_eq!(
            runtime_representation(request),
            RuntimeRepresentation::WireV2
        );
    }

    #[test]
    fn quality_parser_accepts_only_rfc_bounds() {
        assert_eq!(parse_quality("0"), Some(0));
        assert_eq!(parse_quality("0.001"), Some(1));
        assert_eq!(parse_quality("0.999"), Some(999));
        assert_eq!(parse_quality("1.000"), Some(1000));
        assert_eq!(parse_quality("1.001"), None);
        assert_eq!(parse_quality("0.0000"), None);
        assert_eq!(parse_quality(".5"), None);
    }

    #[test]
    fn specificity_determines_quality_before_representations_are_compared() {
        assert_eq!(
            runtime_representation(&request(
                "Accept: application/json;q=0.1, */*;q=1, application/x-hepta-wire;version=2;q=0.5"
            )),
            RuntimeRepresentation::WireV2
        );
        assert_eq!(
            runtime_representation(&request(
                "Accept: application/json;charset=utf-8;q=0, application/json;q=1"
            )),
            RuntimeRepresentation::NotAcceptable
        );
        assert_eq!(
            runtime_representation(&request("Accept: application/json;CHARSET=\"UTF-8\"")),
            RuntimeRepresentation::Json
        );
    }
}
