//! The actual generic input's conversion, iteration, borrowing and drops.
use std::cell::Cell;
use std::cell::RefCell;
use std::rc::Rc;

pub type Events = Rc<RefCell<Vec<String>>>;

#[derive(Clone)]
struct State {
    events: Events,
    fault: u64,
    fired: Rc<Cell<bool>>,
}

impl State {
    fn event(&self, event: String, fault: u64) {
        self.events.borrow_mut().push(event);
        if fault != 0 && self.fault == fault && !self.fired.replace(true) {
            std::panic::panic_any(format!("input fault {fault}"));
        }
    }
}

pub struct Value {
    value: String,
    index: usize,
    key: bool,
    state: State,
}

impl AsRef<str> for Value {
    fn as_ref(&self) -> &str {
        let fault = match (self.index, self.key) {
            (0, true) => 4,
            (0, false) => 5,
            (1, true) => 6,
            (1, false) => 7,
            _ => 0,
        };
        self.state.event(
            format!("as_ref:{}:{}:{:?}", self.index, self.key, self.value),
            fault,
        );
        &self.value
    }
}

impl Drop for Value {
    fn drop(&mut self) {
        let fault = if self.index == 0 && !self.key { 8 } else { 0 };
        self.state.event(
            format!("drop_value:{}:{}:{:?}", self.index, self.key, self.value),
            fault,
        );
    }
}

pub struct Input {
    values: Option<Vec<(Value, Value)>>,
    state: State,
}

pub struct Iter {
    values: std::vec::IntoIter<(Value, Value)>,
    state: State,
    next_index: usize,
}

impl Input {
    pub fn new(values: &[(String, String)], fault: u64) -> (Self, Events) {
        let state = State {
            events: Rc::default(),
            fault,
            fired: Rc::new(Cell::new(false)),
        };
        let data = values
            .iter()
            .enumerate()
            .map(|(index, (key, value))| {
                let key = Value {
                    value: key.clone(),
                    index,
                    key: true,
                    state: state.clone(),
                };
                let value = Value {
                    value: value.clone(),
                    index,
                    key: false,
                    state: state.clone(),
                };
                (key, value)
            })
            .collect();
        let events = state.events.clone();
        (
            Self {
                values: Some(data),
                state,
            },
            events,
        )
    }
}

impl IntoIterator for Input {
    type Item = (Value, Value);
    type IntoIter = Iter;

    fn into_iter(mut self) -> Iter {
        self.state.event("into_iter".to_owned(), 1);
        let values = self.values.take().unwrap_or_default().into_iter();
        Iter {
            values,
            state: self.state.clone(),
            next_index: 0,
        }
    }
}

impl Drop for Input {
    fn drop(&mut self) {
        self.state.event("drop_input".to_owned(), 0);
    }
}

impl Iterator for Iter {
    type Item = (Value, Value);

    fn next(&mut self) -> Option<Self::Item> {
        let fault = match self.next_index {
            0 => 2,
            1 => 3,
            _ => 0,
        };
        self.state.event(format!("next:{}", self.next_index), fault);
        self.next_index += 1;
        let value = self.values.next();
        self.state.event(format!("yield:{}", value.is_some()), 0);
        value
    }

    fn size_hint(&self) -> (usize, Option<usize>) {
        self.state.event("size_hint".to_owned(), 0);
        self.values.size_hint()
    }
}

impl Drop for Iter {
    fn drop(&mut self) {
        self.state.event("drop_iter".to_owned(), 0);
    }
}
