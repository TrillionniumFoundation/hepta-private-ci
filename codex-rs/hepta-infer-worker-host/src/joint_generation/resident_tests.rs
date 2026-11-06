//! Resident reuse must preserve numeric and per-Cell state semantics.

use std::io::Cursor;

use super::*;
use crate::codec::sha256;
use crate::protocol::Command;
use crate::protocol::EmissionLaw;
use crate::protocol::Response;
use crate::protocol::Sampler;

#[path = "proposal_test_support.rs"]
mod support;
use support::Fixture;
use support::request;

fn init(seed: u64) -> Command {
    Command::Init(EmissionLaw {
        seed,
        sampler: Sampler::Mean,
    })
}

fn framed(bytes: &[u8]) -> Vec<u8> {
    let mut result = (bytes.len() as u32).to_le_bytes().to_vec();
    result.extend(bytes);
    result
}

fn assert_same_content(actual: &[u8], expected: Response) -> Result<()> {
    let expected = expected.encode()?;
    // Wall observations differ between executions. Everything else, including
    // the content state's bindings and the exact output prefix, must be equal.
    assert_eq!(&actual[..41], &expected[..41]);
    assert_eq!(
        &actual[73..actual.len() - 64],
        &expected[73..expected.len() - 64]
    );
    assert_eq!(
        sha256(&actual[..actual.len() - 64]).as_bytes(),
        &actual[actual.len() - 64..]
    );
    Ok(())
}

#[test]
fn resident_shares_assets_and_encoding_without_sharing_cell_state() -> Result<()> {
    let fixture = Fixture::new()?;
    let a = fixture.run(&[], &[], init(17))?;
    let advanced = fixture.run(&a.state, &[], Command::Advance(0))?;
    let committed = fixture.run(
        &advanced.state,
        &[],
        Command::Commit {
            modality: 0,
            units: 1,
        },
    )?;
    let mut input = framed(&request(
        &fixture.weights,
        &fixture.public,
        &[],
        &[],
        init(17),
    ));
    input.extend(framed(&request(
        &[],
        &[],
        &a.state,
        &[],
        Command::Advance(0),
    )));
    // Another Cell begins from empty state after A already advanced.
    input.extend(framed(&request(&[], &[], &[], &[], init(23))));
    input.extend(framed(&request(
        &[],
        &[],
        &advanced.state,
        &[],
        Command::Commit {
            modality: 0,
            units: 1,
        },
    )));
    let mut output = Vec::new();
    serve(Cursor::new(input), &mut output)?;
    let mut output = Cursor::new(output);
    for expected in [a, advanced, fixture.run(&[], &[], init(23))?, committed] {
        assert_same_content(
            &read_frame(&mut output)?.ok_or("missing response")?,
            expected,
        )?;
    }
    assert!(read_frame(&mut output)?.is_none());
    Ok(())
}

#[test]
fn resident_refuses_asset_replacement_and_missing_initial_assets() -> Result<()> {
    let fixture = Fixture::new()?;
    let request = request(&fixture.weights, &fixture.public, &[], &[], init(17));
    let mut input = framed(&request);
    input.extend(framed(&request));
    let mut output = Vec::new();
    assert!(serve(Cursor::new(input), &mut output).is_err());
    let mut output = Cursor::new(output);
    assert!(read_frame(&mut output)?.is_some());
    assert!(read_frame(&mut output)?.is_none());
    assert!(
        serve(
            Cursor::new(framed(&support::request(&[], &[], &[], &[], init(17)))),
            Vec::new()
        )
        .is_err()
    );
    Ok(())
}

#[test]
fn resident_rejects_partial_or_oversized_frames_without_a_response() {
    for bytes in [
        vec![1],
        vec![0; 4],
        ((MAX_REQUEST_BYTES + 1) as u32).to_le_bytes().to_vec(),
        vec![9, 0, 0, 0, 1, 2],
    ] {
        let mut output = Vec::new();
        assert!(serve(Cursor::new(bytes), &mut output).is_err());
        assert!(output.is_empty());
    }
    assert!(serve(Cursor::new(Vec::<u8>::new()), Vec::new()).is_ok());
}
