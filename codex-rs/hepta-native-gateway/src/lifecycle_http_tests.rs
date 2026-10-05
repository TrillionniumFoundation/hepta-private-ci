use super::*;

#[test]
fn finite_post_rejects_ambiguous_body_headers_and_trailing_data() {
    let valid = b"POST /api/hepta/agents/lifecycle HTTP/1.1\r\nContent-Type: application/json\r\nContent-Length: 2\r\nAuthorization: finite\r\n\r\n{}";
    let request = parse(valid).unwrap();
    assert_eq!(request.method, "POST");
    assert_eq!(request.body, b"{}");
    for frame in [
        b"POST /api/hepta/agents/lifecycle HTTP/1.1\r\nContent-Length: 2\r\nContent-Length: 2\r\n\r\n{}".as_slice(),
        b"POST /api/hepta/agents/lifecycle HTTP/1.1\r\nContent-Length: 2\r\nTransfer-Encoding: chunked\r\n\r\n{}".as_slice(),
        b"POST /api/hepta/agents/lifecycle HTTP/1.1\r\nContent-Length: 2\r\nAuthorization: a\r\nAuthorization: b\r\n\r\n{}".as_slice(),
        b"POST /api/hepta/agents/lifecycle HTTP/1.1\r\nContent-Length: 2\r\n\r\n{}extra".as_slice(),
        b"POST /api/hepta/agents/lifecycle HTTP/1.1\r\nContent-Length: 3\r\n\r\n{}".as_slice(),
        b"GET /api/hepta/runtime HTTP/1.1\r\nContent-Length: 2\r\n\r\n{}".as_slice(),
        b"POST /api/hepta/agents/lifecycle HTTP/1.1\r\n\r\n".as_slice(),
    ] { assert!(parse(frame).is_err(), "{frame:?}"); }
}
