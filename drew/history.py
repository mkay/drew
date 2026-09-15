# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

"""Undo/redo as a stack of document snapshots.

A document is a short list of small dataclasses, so copying the whole list
at every commit point is cheaper than getting a command pattern right.
Annotation ids survive the copy, which is how the canvas re-finds its
selection after a restore.
"""

import copy


class History:
    def __init__(self, limit=200):
        self._undo = []
        self._redo = []
        self._limit = limit

    def reset(self, annotations):
        self._undo = [copy.deepcopy(annotations)]
        self._redo = []

    def commit(self, annotations):
        """Record the state after a change."""
        self._undo.append(copy.deepcopy(annotations))
        del self._undo[:-self._limit]
        self._redo = []

    @property
    def can_undo(self):
        return len(self._undo) > 1

    @property
    def can_redo(self):
        return bool(self._redo)

    def undo(self):
        """Return the previous state, or None."""
        if not self.can_undo:
            return None
        self._redo.append(self._undo.pop())
        return copy.deepcopy(self._undo[-1])

    def redo(self):
        if not self.can_redo:
            return None
        state = self._redo.pop()
        self._undo.append(state)
        return copy.deepcopy(state)
