use super::*;

#[test]
fn cjk_emoji_combining_and_newline_use_original_sdk_graphemes() {
    let value = "中文👨‍👩‍👧‍👦e\u{301}\n末行\n";
    let (nodes, runs) = build(value, |index| NodeId(index as u64 + 1));
    assert_eq!(nodes.len(), 3);
    for byte in [0, 3, 6, 31, 34, 35, 38, 41, 42] {
        let position = position(&runs, byte).unwrap();
        assert_eq!(
            selection(
                &runs,
                TextSelection {
                    anchor: position,
                    focus: position
                }
            ),
            Some((byte, byte))
        );
    }
    assert!(position(&runs, 7).is_none());
    assert!(position(&runs, 32).is_none());
}

#[test]
fn old_run_or_out_of_range_selection_is_rejected() {
    let (_, runs) = build("中文", |index| NodeId(index as u64 + 10));
    let valid = position(&runs, 3).unwrap();
    for invalid in [
        TextPosition {
            node: NodeId(9),
            character_index: 1,
        },
        TextPosition {
            node: NodeId(10),
            character_index: 3,
        },
    ] {
        assert_eq!(
            selection(
                &runs,
                TextSelection {
                    anchor: valid,
                    focus: invalid
                }
            ),
            None
        );
    }
}
