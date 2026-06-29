"""Candidate edit state machine and safe-apply public API."""

from ._core_impl import (
    apply_approved_candidates,
    approve_candidate,
    candidate_summary,
    edit_candidate,
    inspect_record,
    load_candidates,
    propose_candidates,
    reject_candidate,
    render_apply_diff,
    restore_backup,
    verify_candidate_anchor,
)

__all__ = [
    "apply_approved_candidates",
    "approve_candidate",
    "candidate_summary",
    "edit_candidate",
    "inspect_record",
    "load_candidates",
    "propose_candidates",
    "reject_candidate",
    "render_apply_diff",
    "restore_backup",
    "verify_candidate_anchor",
]
