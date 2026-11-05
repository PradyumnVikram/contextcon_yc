"""Test isolation: no network, no repo-root clearance.db, deterministic CSL. SHARED (both teammates' tests rely on it)."""
from pathlib import Path

import pytest

from clearance import config, crustdata_client
from clearance import screening
from clearance.screening import csl

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(config, "CRUSTDATA_API_KEY", "")
    monkeypatch.setattr(csl, "CSL_CSV", FIXTURES / "csl_sample.csv")
    screening.reload()
    client = crustdata_client.CrustdataClient.open(":memory:", api_key="")
    crustdata_client.set_client(client)
    yield client
    crustdata_client.set_client(None)
    screening.reload()
