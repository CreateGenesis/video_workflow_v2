"""In-process platform tests. SQLite stands in when PostgreSQL is not reachable."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    url = "sqlite:///" + str(tmp_path / "platform.db")
    monkeypatch.setenv("CVGEN_PLATFORM_DATABASE_URL", url)
    from cvplatform import db

    db.reset_engine()
    db.init_schema()
    from cvplatform.app import app

    with TestClient(app) as test:
        yield test
    db.reset_engine()
