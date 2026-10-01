use std::io;
use std::pin::Pin;
use std::task::Context as TaskContext;
use std::task::Poll;

use pretty_assertions::assert_eq;
use tokio::io::ReadBuf;

use super::*;

const HEAD: &[u8] = b"GET /api/hepta/runtime HTTP/1.1\r\nAccept: application/x-hepta-wire; version=2\r\n\r\n";

struct Fragmented<'a> {
    remaining: &'a [u8],
    chunk: usize,
    consumed: usize,
}

impl AsyncRead for Fragmented<'_> {
    fn poll_read(
        self: Pin<&mut Self>,
        _context: &mut TaskContext<'_>,
        output: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        let reader = self.get_mut();
        let count = reader
            .remaining
            .len()
            .min(reader.chunk)
            .min(output.remaining());
        output.put_slice(&reader.remaining[..count]);
        reader.remaining = &reader.remaining[count..];
        reader.consumed += count;
        Poll::Ready(Ok(()))
    }
}

#[tokio::test]
async fn http_accept_head_framing_is_invariant_to_fragment_size() -> Result<()> {
    let mut bytes = HEAD.to_vec();
    bytes.extend_from_slice(b"\xff\xfeunparsed-body-or-next-request");
    for chunk in 1..=bytes.len() {
        let mut reader = Fragmented {
            remaining: &bytes,
            chunk,
            consumed: 0,
        };
        assert_eq!(read_request(&mut reader).await?, HEAD);
    }
    Ok(())
}

#[tokio::test]
async fn http_accept_head_at_exact_ceiling_is_admitted_without_overreading() -> Result<()> {
    let mut bytes = vec![b'x'; MAX_REQUEST_BYTES - 4];
    bytes.extend_from_slice(b"\r\n\r\ntrailing");
    let mut reader = Fragmented {
        remaining: &bytes,
        chunk: 4096,
        consumed: 0,
    };
    assert_eq!(read_request(&mut reader).await?, &bytes[..MAX_REQUEST_BYTES]);
    assert_eq!(reader.consumed, MAX_REQUEST_BYTES);
    assert_eq!(reader.remaining, b"trailing");
    Ok(())
}

#[tokio::test]
async fn http_accept_oversize_head_stops_at_budget_not_after_an_extra_read() {
    let bytes = vec![b'x'; MAX_REQUEST_BYTES + 2048];
    let mut reader = Fragmented {
        remaining: &bytes,
        chunk: 4096,
        consumed: 0,
    };
    assert!(read_request(&mut reader).await.is_err());
    assert_eq!(reader.consumed, MAX_REQUEST_BYTES);
}

#[tokio::test]
async fn http_accept_truncated_head_never_becomes_a_request() {
    for end in 0..HEAD.len() {
        let mut reader = Fragmented {
            remaining: &HEAD[..end],
            chunk: 7,
            consumed: 0,
        };
        assert!(read_request(&mut reader).await.is_err());
    }
}

#[tokio::test]
async fn http_accept_next_request_cannot_change_the_first_representation() -> Result<()> {
    let mut bytes = HEAD.to_vec();
    bytes.extend_from_slice(b"GET / HTTP/1.1\r\nAccept: application/json\r\n\r\n");
    let mut reader = Fragmented {
        remaining: &bytes,
        chunk: bytes.len(),
        consumed: 0,
    };
    let first = read_request(&mut reader).await?;
    assert_eq!(first, HEAD);
    assert_eq!(
        crate::http_accept::runtime_representation(std::str::from_utf8(&first)?),
        crate::http_accept::RuntimeRepresentation::WireV2,
    );
    Ok(())
}
