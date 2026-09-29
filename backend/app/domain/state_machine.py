"""Complaint status state machine.

Deliberately an explicit transition table rather than a chain of ifs: the legal
transitions are data, so they can be read, tested and rendered by the API
(``GET /api/complaints/{id}`` exposes ``allowed_transitions``) without any
caller re-implementing the rules. The frontend never hardcodes this.
"""
from __future__ import annotations

from app.domain.enums import Status

#: Directed graph of legal transitions. A status whose value is an empty
#: frozenset is terminal.
TRANSITIONS: dict[Status, frozenset[Status]] = {
    Status.OPEN: frozenset({Status.IN_PROGRESS, Status.REJECTED}),
    Status.IN_PROGRESS: frozenset({Status.RESOLVED, Status.REJECTED}),
    Status.RESOLVED: frozenset(),
    Status.REJECTED: frozenset(),
}

TERMINAL_STATUSES: frozenset[Status] = frozenset(
    s for s, targets in TRANSITIONS.items() if not targets
)


class InvalidTransition(Exception):
    """Raised when a caller attempts a transition not in the table.

    Carries both endpoints so the route layer can render a 409 that names the
    attempted transition rather than a generic failure.
    """

    def __init__(self, current: Status, attempted: Status) -> None:
        self.current = current
        self.attempted = attempted
        allowed = sorted(t.value for t in TRANSITIONS[current])
        allowed_text = ", ".join(allowed) if allowed else "none (terminal status)"
        super().__init__(
            f"Invalid status transition {current.value} -> {attempted.value}. "
            f"Allowed from {current.value}: {allowed_text}."
        )


def can_transition(current: Status, attempted: Status) -> bool:
    return attempted in TRANSITIONS[current]


def assert_transition(current: Status, attempted: Status) -> None:
    if not can_transition(current, attempted):
        raise InvalidTransition(current, attempted)


def allowed_transitions(current: Status) -> list[Status]:
    return sorted(TRANSITIONS[current], key=lambda s: s.value)
