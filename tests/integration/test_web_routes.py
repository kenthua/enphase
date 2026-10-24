import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src")))

import web


@pytest.fixture
def mock_enphase_client(monkeypatch):
    client = MagicMock()
    client.get_status.return_value = {
        "timestamp": "2026-10-24T18:00:26.617179135Z",
        "data": {
            "profile": "self-consumption",
            "batteryBackupPercentage": 10,
            "operationModeSubType": "prioritize-energy",
            "stormGuardState": "disabled",
            "buybackExportPlan": "nem",
            "veryLowSoc": 10,
            "dtgControl": {"enabled": True},
            "cfgControl": {"enabled": False},
            "isBatteryChangePending": False,
            "siteProfileStatus": "READY",
            "previousBatteryBackupPercentage": {
                "self-consumption": 10,
                "backup_only": 100,
                "ai_optimisation": 10,
            },
        },
    }
    client.set_self_consumption.return_value = {
        "status": "ok",
        "profile": "self-consumption",
        "batteryBackupPercentage": 10,
        "response": {"message": "success"},
    }
    client.set_full_backup.return_value = {
        "status": "ok",
        "profile": "backup_only",
        "batteryBackupPercentage": 100,
        "response": {"message": "success"},
    }
    client.set_ai_optimization.return_value = {
        "status": "ok",
        "profile": "ai_optimisation",
        "batteryBackupPercentage": 10,
        "response": {"message": "success"},
    }
    monkeypatch.setattr(web, "_client", client)
    return client


@pytest.fixture
def test_client(mock_enphase_client):
    web.app.config["TESTING"] = True
    with web.app.test_client() as client:
        yield client


def test_healthz_route(test_client):
    resp = test_client.get("/healthz")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["version"] == "1.1.0"


def test_status_route(test_client, mock_enphase_client):
    resp = test_client.get("/status")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["version"] == "1.1.0"
    assert body["profile"] == "self-consumption"
    assert body["profileDisplayName"] == "Self-Consumption"
    assert body["batteryBackupPercentage"] == 10
    assert body["stormGuardState"] == "disabled"
    assert body["buybackExportPlan"] == "nem"
    assert body["veryLowSoc"] == 10
    assert body["exportToGridEnabled"] is True
    assert body["chargeFromGridEnabled"] is False
    assert body["siteProfileStatus"] == "READY"
    mock_enphase_client.get_status.assert_called_once()


def test_self_consumption_route(test_client, mock_enphase_client):
    resp = test_client.get("/self-consumption?reserve=20")
    assert resp.status_code == 200
    assert resp.get_json()["profile"] == "self-consumption"
    mock_enphase_client.set_self_consumption.assert_called_once_with(reserve=20)


def test_self_consumption_invalid_reserve_returns_400(test_client):
    resp = test_client.get("/self-consumption?reserve=3")
    assert resp.status_code == 400
    assert "reserve must be between 5 and 100" in resp.get_json()["message"]


def test_full_backup_route(test_client, mock_enphase_client):
    resp = test_client.get("/full-backup")
    assert resp.status_code == 200
    assert resp.get_json()["profile"] == "backup_only"
    mock_enphase_client.set_full_backup.assert_called_once()


def test_ai_optimization_routes(test_client, mock_enphase_client):
    resp1 = test_client.get("/ai-optimization?reserve=10")
    assert resp1.status_code == 200
    assert resp1.get_json()["profile"] == "ai_optimisation"
    mock_enphase_client.set_ai_optimization.assert_called_with(
        reserve=10,
        operation_mode_sub_type=None,
    )

    resp2 = test_client.post(
        "/ai-optimisation",
        json={"reserve": 15, "operationModeSubType": "prioritize-energy"},
    )
    assert resp2.status_code == 200
    mock_enphase_client.set_ai_optimization.assert_called_with(
        reserve=15,
        operation_mode_sub_type="prioritize-energy",
    )


def test_error_handling_returns_500(test_client, mock_enphase_client):
    mock_enphase_client.set_full_backup.side_effect = RuntimeError("Enphase API unreachable")
    resp = test_client.get("/full-backup")
    assert resp.status_code == 500
    assert resp.get_json()["status"] == "error"
