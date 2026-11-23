
#[cfg(test)]
mod native_canonical_comparison {
    use super::super::super::Error;
    use super::super::super::wire::{Action, MAX_BYTES, Purpose, Request, Status};
    use codex_hepta_types::Digest32;
    use std::fs;
    use std::path::PathBuf;

    const PAYLOAD: &[u8] = b"original head wire comparison\x00\xff";
    const PREFIX: usize = 55;

    fn request() -> Request {
        Request::new(Purpose::Head, Action::Readback, 7, Digest32::from_array([0x37; 32]))
            .expect("valid fixed request")
    }

    fn corpus() -> PathBuf {
        PathBuf::from(std::env::var_os("CANONICAL_HEAD_CORPUS").expect("shared corpus"))
    }

    fn canonical_frame(tag: u8, data: &[u8]) -> Vec<u8> {
        let mut bytes = Vec::from(b"HARPC001".as_slice());
        bytes.extend_from_slice(&[2, 1]);
        bytes.extend_from_slice(&7u64.to_be_bytes());
        bytes.extend_from_slice(&[0x37; 32]);
        bytes.push(tag);
        bytes.extend_from_slice(&u32::try_from(data.len()).unwrap().to_be_bytes());
        bytes.extend_from_slice(data);
        bytes
    }

    fn statuses() -> [(u8, Status, &'static [u8]); 5] {
        [
            (1, Status::Completed, PAYLOAD),
            (2, Status::Missing, &[]),
            (3, Status::Pending, &[]),
            (4, Status::Unavailable, &[]),
            (5, Status::ReadbackRequired, &[]),
        ]
    }

    fn check_status(req: &Request, bytes: &[u8], tag: u8, size: usize) {
        let result = req.read_response(bytes);
        match (tag, size, result) {
            (1, 1.., Ok(data)) => {
                assert_eq!(data, &bytes[PREFIX..]);
                assert_eq!(data.as_ptr(), bytes[PREFIX..].as_ptr());
            }
            (2, 0, Err(Error::Missing))
            | (3, 0, Err(Error::Pending))
            | (4, 0, Err(Error::Unavailable))
            | (5, 0, Err(Error::ReadbackRequired)) => {}
            (_, _, Err(Error::Binding("canonical original Artifact state")))
                if !(tag == 1 && size > 0 || (2..=5).contains(&tag) && size == 0) => {}
            (_, _, unexpected) => panic!("unexpected result for tag {tag} size {size}: {unexpected:?}"),
        }
    }

    #[test]
    fn original_codec_emits_five_canonical_responses() {
        let req = request();
        let output = corpus();
        for (tag, status, data) in statuses() {
            let encoded = req.response(status, data).expect("canonical encoder");
            assert_eq!(encoded, canonical_frame(tag, data));
            check_status(&req, &encoded, tag, data.len());
            fs::write(output.join(format!("{tag}.bin")), encoded).expect("record response");
        }
    }

    #[test]
    fn original_codec_reads_other_products_five_responses() {
        let req = request();
        let input = corpus();
        for (tag, status, data) in statuses() {
            let frame = fs::read(input.join(format!("{tag}.bin"))).expect("peer's actual frame");
            assert_eq!(frame, canonical_frame(tag, data));
            check_status(&req, &frame, tag, data.len());
            assert_eq!(req.response(status, data).expect("re-encode"), frame);
        }
    }

    #[test]
    fn original_codec_checks_status_partition_and_bounds() {
        let req = request();
        for tag in u8::MIN..=u8::MAX {
            for payload in [&[][..], &[0xa5][..]] {
                let frame = canonical_frame(tag, payload);
                check_status(&req, &frame, tag, payload.len());
            }
        }
        assert_eq!(MAX_BYTES, 16_384);
        for length in [MAX_BYTES - PREFIX - 1, MAX_BYTES - PREFIX] {
            let data = vec![0xa5; length];
            let max = req.response(Status::Completed, &data).expect("bounded encoder");
            assert_eq!(max, canonical_frame(1, &data));
            check_status(&req, &max, 1, length);
        }
        let excess = vec![0xa5; MAX_BYTES - PREFIX + 1];
        assert!(matches!(req.response(Status::Completed, &excess),
                         Err(Error::Binding("bounded complete original Artifact response"))));
        assert!(matches!(req.read_response(&canonical_frame(1, &excess)),
                         Err(Error::Binding("same original Artifact response"))));
        assert!(matches!(req.response(Status::Completed, &[]),
                         Err(Error::Binding("bounded complete original Artifact response"))));
        for (_, status, _) in statuses().into_iter().skip(1) {
            assert!(matches!(req.response(status, &[1]),
                             Err(Error::Binding("no material in unresolved original state"))));
        }
        let mut mismatch = canonical_frame(1, &[0xa5]);
        mismatch[51..55].copy_from_slice(&2u32.to_be_bytes());
        assert!(matches!(req.read_response(&mismatch), Err(Error::Unavailable)));
        let mut different_request = canonical_frame(1, &[0xa5]);
        different_request[17] ^= 1;
        assert!(matches!(req.read_response(&different_request),
                         Err(Error::Binding("same original Artifact response"))));
        assert!(matches!(req.read_response(&canonical_frame(2, &[])[..54]),
                         Err(Error::Binding("same original Artifact response"))));
    }
}
