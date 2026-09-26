"""tests/test_metadata.py — /v1/metadata tests"""
import pytest
from tests.conftest import *


def test_metadata_returns_200(client):
    r = client.get("/v1/metadata")
    assert r.status_code == 200


def test_metadata_schema(client):
    r = client.get("/v1/metadata")
    data = r.json()
    for field in ("team_name", "team_members", "model", "approach", "contact_email", "version", "submitted_at"):
        assert field in data, f"Missing field: {field}"


def test_metadata_team_name_not_empty(client):
    r = client.get("/v1/metadata")
    assert r.json()["team_name"] != ""


def test_metadata_version_format(client):
    r = client.get("/v1/metadata")
    version = r.json()["version"]
    parts = version.split(".")
    assert len(parts) == 3, "Version should be X.Y.Z format"
