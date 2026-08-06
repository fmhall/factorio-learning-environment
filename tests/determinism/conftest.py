"""Deterministic-mode tests manage their own instance.

Shadow the repo-level autouse _reset_between_tests fixture (which depends on
the shared real-time session instance) with a no-op.
"""

import pytest


@pytest.fixture(autouse=True)
def _reset_between_tests():
    yield
