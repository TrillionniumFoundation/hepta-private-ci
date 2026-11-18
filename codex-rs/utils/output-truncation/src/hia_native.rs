//! Transport and value ownership for the HIA per-item output-budget machine.
//!
//! HIA owns costs, decisions and counters. Rust keeps the original allocation,
//! item order, audio callbacks, text truncation and complete opaque values.
//! No input text or media is copied into the fixed numeric request.

use crate::TruncationPolicy;
use crate::truncate_text;
use codex_protocol::models::FunctionCallOutputContentItem;

const STATE_WORDS: usize = 9;
const RESULT_WORDS: usize = 11;
const RESULT_BYTES: usize = RESULT_WORDS * 8;

#[derive(Clone, Copy)]
#[repr(u64)]
enum Operation {
    Init = 0,
    Item = 1,
    Snippet = 2,
    Finish = 3,
}

#[repr(u64)]
enum ItemKind {
    Text = 0,
    Audio = 1,
    Image = 2,
    Encrypted = 3,
}

#[derive(Debug, PartialEq, Eq)]
enum Decision {
    Keep,
    Omit,
    Truncate(usize),
}

unsafe extern "C" {
    fn codex_hia_output_item_budget(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

fn invoke(words: &[u64]) -> [u64; RESULT_WORDS] {
    assert!(matches!(words.len(), 5 | 10 | 11 | 12));
    let mut source = [0_u8; 96];
    for (value, bytes) in words.iter().zip(source.chunks_exact_mut(8)) {
        bytes.copy_from_slice(&value.to_le_bytes());
    }
    let mut output = [0_u8; RESULT_BYTES];
    let mut workspace = [];
    // SAFETY: separate live stack buffers cover every advertised range for
    // this synchronous call. The source contains only a fixed numeric frame.
    // The HIA entry checks capacities before storing and retains no pointers.
    let status = unsafe {
        codex_hia_output_item_budget(
            source.as_ptr(),
            (words.len() * 8) as u64,
            output.as_mut_ptr(),
            RESULT_BYTES as u64,
            workspace.as_mut_ptr(),
            workspace.len() as u64,
        )
    };
    // Compare the full return, including any high-word wrapper rejection.
    assert_eq!(status, RESULT_BYTES as u64, "HIA item-budget call failed");
    let mut result = [0_u64; RESULT_WORDS];
    for (word, bytes) in result.iter_mut().zip(output.chunks_exact(8)) {
        let mut encoded = [0_u8; 8];
        encoded.copy_from_slice(bytes);
        *word = u64::from_le_bytes(encoded);
    }
    result
}

struct Budget {
    state: [u64; STATE_WORDS],
}

impl Budget {
    fn new(policy: TruncationPolicy, total: usize) -> Self {
        let (mode, budget) = match policy {
            TruncationPolicy::Bytes(_) => (0, policy.byte_budget()),
            TruncationPolicy::Tokens(_) => (1, policy.token_budget()),
        };
        let budget = budget as u64;
        let total = total as u64;
        let result = invoke(&[Operation::Init as u64, 1, mode, budget, total]);
        assert_eq!(
            result,
            [1, 0, mode, budget, budget, total, 0, 0, 0, 0, 0],
            "HIA initial item-budget state is invalid"
        );
        let mut state = [0_u64; STATE_WORDS];
        state.copy_from_slice(&result[..STATE_WORDS]);
        Self { state }
    }

    fn transition(&mut self, operation: Operation, extra: &[u64]) -> [u64; 2] {
        assert!(extra.len() <= 2);
        let mut request = [0_u64; 12];
        request[0] = operation as u64;
        request[1..10].copy_from_slice(&self.state);
        request[10..10 + extra.len()].copy_from_slice(extra);
        let result = invoke(&request[..10 + extra.len()]);
        assert_eq!(
            [result[0], result[2], result[3], result[5]],
            [1, self.state[2], self.state[3], self.state[5]],
            "HIA item-budget identity changed"
        );
        assert!(
            result[1] <= 2
                && result[4] <= result[3]
                && result[6] <= result[5]
                && result[7] <= result[6]
                && result[8] <= result[6] - result[7],
            "HIA item-budget state is out of bounds"
        );
        let pending = matches!(operation, Operation::Item) && result[9] == 3;
        if pending || matches!(operation, Operation::Finish) {
            assert_eq!(result[6], self.state[6]);
        } else {
            assert_eq!(self.state[6].checked_add(1), Some(result[6]));
        }
        self.state.copy_from_slice(&result[..STATE_WORDS]);
        [result[9], result[10]]
    }

    fn decision(&self, action: [u64; 2]) -> Decision {
        match action {
            [1, 0] => {
                assert_eq!(self.state[1], 0, "HIA keep state is not ready");
                Decision::Keep
            }
            [2, 0] => {
                assert_eq!(self.state[1], 0, "HIA omission state is not ready");
                Decision::Omit
            }
            [3, budget] => {
                assert_eq!(self.state[1], 1, "HIA snippet state is not pending");
                assert!(budget > 0 && budget == self.state[4]);
                Decision::Truncate(count(budget))
            }
            _ => panic!("HIA item-budget action is invalid"),
        }
    }

    fn item(&mut self, kind: ItemKind, value: usize) -> Decision {
        let action = self.transition(Operation::Item, &[kind as u64, value as u64]);
        self.decision(action)
    }

    fn snippet(&mut self, length: usize) -> Decision {
        let action = self.transition(Operation::Snippet, &[length as u64]);
        assert!(matches!(action, [1 | 2, 0]));
        self.decision(action)
    }

    fn finish(mut self) -> (usize, usize) {
        let action = self.transition(Operation::Finish, &[]);
        assert_eq!(action, [4, 0], "HIA finish action is invalid");
        assert_eq!(self.state[1], 2, "HIA finish state is not finished");
        assert_eq!(self.state[6], self.state[5]);
        (count(self.state[7]), count(self.state[8]))
    }
}

fn count(value: u64) -> usize {
    match usize::try_from(value) {
        Ok(value) => value,
        Err(_) => panic!("HIA item-budget count does not fit usize"),
    }
}

pub(super) fn truncate(
    items: &[FunctionCallOutputContentItem],
    policy: TruncationPolicy,
    estimate_audio_token_count: impl Fn(&str) -> usize,
) -> Vec<FunctionCallOutputContentItem> {
    let mut out = Vec::with_capacity(items.len());
    let mut budget = Budget::new(policy, items.len());

    for item in items {
        match item {
            FunctionCallOutputContentItem::InputText { text } => {
                match budget.item(ItemKind::Text, text.len()) {
                    Decision::Keep => {
                        out.push(FunctionCallOutputContentItem::InputText { text: text.clone() });
                    }
                    Decision::Omit => {}
                    Decision::Truncate(remaining) => {
                        let snippet_policy = match policy {
                            TruncationPolicy::Bytes(_) => TruncationPolicy::Bytes(remaining),
                            TruncationPolicy::Tokens(_) => TruncationPolicy::Tokens(remaining),
                        };
                        let snippet = truncate_text(text, snippet_policy);
                        if budget.snippet(snippet.len()) == Decision::Keep {
                            out.push(FunctionCallOutputContentItem::InputText { text: snippet });
                        }
                    }
                }
            }
            FunctionCallOutputContentItem::InputImage { image_url, detail } => {
                assert_eq!(budget.item(ItemKind::Image, /*value*/ 0), Decision::Keep);
                out.push(FunctionCallOutputContentItem::InputImage {
                    image_url: image_url.clone(),
                    detail: *detail,
                });
            }
            FunctionCallOutputContentItem::InputAudio { audio_url } => {
                let token_cost = estimate_audio_token_count(audio_url);
                match budget.item(ItemKind::Audio, token_cost) {
                    Decision::Keep => {
                        out.push(FunctionCallOutputContentItem::InputAudio {
                            audio_url: audio_url.clone(),
                        });
                    }
                    Decision::Omit => {}
                    Decision::Truncate(_) => panic!("HIA audio requested text truncation"),
                }
            }
            FunctionCallOutputContentItem::EncryptedContent { encrypted_content } => {
                assert_eq!(
                    budget.item(ItemKind::Encrypted, /*value*/ 0),
                    Decision::Keep
                );
                out.push(FunctionCallOutputContentItem::EncryptedContent {
                    encrypted_content: encrypted_content.clone(),
                });
            }
        }
    }

    let (omitted_text_items, omitted_audio_items) = budget.finish();
    if omitted_text_items > 0 {
        out.push(FunctionCallOutputContentItem::InputText {
            text: format!("[omitted {omitted_text_items} text items ...]"),
        });
    }
    if omitted_audio_items > 0 {
        out.push(FunctionCallOutputContentItem::InputText {
            text: format!("[omitted {omitted_audio_items} audio items ...]"),
        });
    }
    out
}
