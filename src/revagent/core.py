"""Compatibility facade for the public RevAgent API.

New integrations should prefer subsystem modules such as ``workspace``,
``latex``, ``reviews``, ``candidates``, ``planning``, ``proofs``,
``experiments``, ``rendering``, and ``validation``.
"""

from ._core_impl import *  # noqa: F403

