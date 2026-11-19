use super::*;

#[test]
fn every_control_and_output_frame_rejects_an_old_protocol() {
    let messages = [
        Message::Terminate {
            payload: EmptyPayload {},
        },
        Message::CloseStdin {
            payload: EmptyPayload {},
        },
        Message::Stdin {
            payload: StdinPayload {
                data_b64: encode_bytes(b"stdin"),
            },
        },
        Message::Output {
            payload: OutputPayload {
                data_b64: encode_bytes(b"output"),
                stream: OutputStream::Stdout,
            },
        },
    ];
    for message in messages {
        let frame = FramedMessage {
            version: IPC_PROTOCOL_VERSION - 1,
            message,
        };
        let mut bytes = Vec::new();
        write_frame(&mut bytes, &frame).unwrap();
        assert!(read_frame(bytes.as_slice()).is_err());
    }
}
