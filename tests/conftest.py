"""Shared fixtures.

The offline gate is `pytest -m "not network"`. Any test that touches the live
SatNOGS API must be marked `network` or it will break the clean-clone claim.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(autouse=True)
def _block_network(request, monkeypatch):
    """Make an unmarked test that reaches for the network fail loudly.

    Without this, a test that quietly depends on a live API passes locally and
    the offline replay claim is false. Mark the test `network` if it genuinely
    needs the API.
    """
    if request.node.get_closest_marker("network"):
        return

    import socket

    def _refuse(*args, **kwargs):
        raise RuntimeError(
            "network access from an unmarked test. Add @pytest.mark.network, "
            "or use a fixture. The offline replay gate depends on this."
        )

    monkeypatch.setattr(socket, "socket", _refuse)
