// Copyright 2026 The AccessKit Authors. All rights reserved.
// Licensed under the Apache License, Version 2.0 (found in
// the LICENSE-APACHE file) or the MIT license (found in
// the LICENSE-MIT file), at your option.

use accesskit_atspi_common::PlatformNode;
use zbus::fdo;
use zbus::interface;

pub(crate) struct EditableTextInterface {
    node: PlatformNode,
}

impl EditableTextInterface {
    pub fn new(node: PlatformNode) -> Self {
        Self { node }
    }

    fn map_error(&self) -> impl '_ + FnOnce(accesskit_atspi_common::Error) -> fdo::Error {
        |error| crate::util::map_error_from_node(&self.node, error)
    }
}

#[interface(name = "org.a11y.atspi.EditableText")]
impl EditableTextInterface {
    fn set_text_contents(&self, new_contents: &str) -> fdo::Result<bool> {
        self.node
            .set_text_contents(new_contents)
            .map_err(self.map_error())
    }

    fn insert_text(&self, position: i32, text: &str, length: i32) -> fdo::Result<bool> {
        self.node
            .insert_text(position, text, length)
            .map_err(self.map_error())
    }

    fn copy_text(&self, start_pos: i32, end_pos: i32) -> fdo::Result<()> {
        match self
            .node
            .copy_text(start_pos, end_pos)
            .map_err(self.map_error())?
        {
            true => Ok(()),
            false => Err(fdo::Error::Failed("Text copy was refused".into())),
        }
    }

    fn cut_text(&self, start_pos: i32, end_pos: i32) -> fdo::Result<bool> {
        self.node
            .cut_text(start_pos, end_pos)
            .map_err(self.map_error())
    }

    fn delete_text(&self, start_pos: i32, end_pos: i32) -> fdo::Result<bool> {
        self.node
            .delete_text(start_pos, end_pos)
            .map_err(self.map_error())
    }

    fn paste_text(&self, _position: i32) -> fdo::Result<bool> {
        // The original Makepad API has no request-scoped clipboard read. Do
        // not emulate keys, read another window, or report an unperformed edit.
        Ok(false)
    }
}
