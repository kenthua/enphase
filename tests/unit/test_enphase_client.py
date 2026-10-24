import base64
import json
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src")))

from enphase_client import (
    PROFILE_AI_OPTIMIZATION,
    PROFILE_FULL_BACKUP,
    PROFILE_SELF_CONSUMPTION,
    EnphaseCloudClient,
    decode_jwt_claims,
)


def _make_jwt(claims: dict) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256"}).encode()).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"{header}.{payload}.sig"


def test_decode_jwt_claims_extracts_enl_uid():
    token = _make_jwt({"enl_uid": "4929788", "exp": 9999999999})
    claims = decode_jwt_claims(token)
    assert claims["enl_uid"] == "4929788"
    assert claims["exp"] == 9999999999


def test_decode_jwt_claims_invalid_token():
    with pytest.raises(ValueError, match="Invalid JWT token format"):
        decode_jwt_claims("not-a-jwt")


def test_login_and_get_status_caches_session(tmp_path):
    cache_file = str(tmp_path / "session.json")
    client = EnphaseCloudClient(
        username="user@example.com",
        password=os.urandom(4).hex(),
        site_id="5482227",
        cache_file=cache_file,
    )

    jwt_token = _make_jwt({"enl_uid": "4929788", "exp": 9999999999})

    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {"manager_token": "mgr-token-123"}

    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"token": jwt_token}

    mock_profile_resp = MagicMock()
    mock_profile_resp.status_code = 200
    mock_profile_resp.headers = {"X-Csrf-Token": "xsrf-abc"}
    mock_profile_resp.json.return_value = {
        "type": "profile-details",
        "data": {
            "profile": "self-consumption",
            "batteryBackupPercentage": 10,
            "operationModeSubType": "prioritize-energy",
            "previousBatteryBackupPercentage": {
                "self-consumption": 10,
                "backup_only": 100,
                "ai_optimisation": 10,
            },
        },
    }

    client.session.post = MagicMock(return_value=mock_post_resp)
    client.session.get = MagicMock(side_effect=[mock_token_resp, mock_profile_resp])

    status = client.get_status()
    assert status["data"]["profile"] == "self-consumption"
    assert client.user_id == "4929788"
    assert os.path.exists(cache_file)

    # Reload from cache without re-logging in
    client2 = EnphaseCloudClient(
        username="user@example.com",
        password=os.urandom(4).hex(),
        site_id="5482227",
        cache_file=cache_file,
    )
    assert client2.user_id == "4929788"
    assert client2.jwt_token == jwt_token
    assert client2.manager_token == "mgr-token-123"


def test_set_profile_modes_and_reserve_resolution(tmp_path):
    jwt_token = _make_jwt({"enl_uid": "4929788", "exp": 9999999999})
    client = EnphaseCloudClient(
        username="user@example.com",
        password=os.urandom(4).hex(),
        site_id="5482227",
        user_id="4929788",
        cache_file=str(tmp_path / "session.json"),
    )
    client.jwt_token = jwt_token
    client.manager_token = "mgr-token-123"
    client.jwt_exp = 9999999999

    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.headers = {"X-Csrf-Token": "xsrf-xyz"}
    mock_get_resp.json.return_value = {
        "data": {
            "profile": "self-consumption",
            "batteryBackupPercentage": 10,
            "operationModeSubType": "prioritize-energy",
            "previousBatteryBackupPercentage": {
                "self-consumption": 15,
                "backup_only": 100,
                "ai_optimisation": 10,
            },
        }
    }

    mock_put_resp = MagicMock()
    mock_put_resp.status_code = 200
    mock_put_resp.content = b'{"message":"success"}'
    mock_put_resp.json.return_value = {"message": "success"}

    client.session.get = MagicMock(return_value=mock_get_resp)
    client.session.put = MagicMock(return_value=mock_put_resp)

    # 1. Self-consumption preserves previousBatteryBackupPercentage (15%) when not overridden
    res_sc = client.set_self_consumption()
    assert res_sc["profile"] == PROFILE_SELF_CONSUMPTION
    assert res_sc["batteryBackupPercentage"] == 15
    _, put_kwargs = client.session.put.call_args
    assert put_kwargs["json"] == {"profile": "self-consumption", "batteryBackupPercentage": 15}
    assert put_kwargs["headers"]["X-XSRF-Token"] == "xsrf-xyz"

    # 2. Full backup uses 100%
    res_fb = client.set_full_backup()
    assert res_fb["profile"] == PROFILE_FULL_BACKUP
    assert res_fb["batteryBackupPercentage"] == 100
    _, put_kwargs = client.session.put.call_args
    assert put_kwargs["json"] == {"profile": "backup_only", "batteryBackupPercentage": 100}

    # 3. AI Optimization includes operationModeSubType
    res_ai = client.set_ai_optimization()
    assert res_ai["profile"] == PROFILE_AI_OPTIMIZATION
    assert res_ai["batteryBackupPercentage"] == 10
    _, put_kwargs = client.session.put.call_args
    assert put_kwargs["json"] == {
        "profile": "ai_optimisation",
        "batteryBackupPercentage": 10,
        "operationModeSubType": "prioritize-energy",
    }


def test_reauthenticates_on_401(tmp_path):
    jwt_token = _make_jwt({"enl_uid": "4929788", "exp": 9999999999})
    client = EnphaseCloudClient(
        username="user@example.com",
        password=os.urandom(4).hex(),
        site_id="5482227",
        user_id="4929788",
        cache_file=str(tmp_path / "session.json"),
    )
    client.jwt_token = "expired-jwt"
    client.manager_token = "expired-mgr"
    client.jwt_exp = 9999999999

    resp_401 = MagicMock()
    resp_401.status_code = 401

    resp_login = MagicMock()
    resp_login.status_code = 200
    resp_login.json.return_value = {"manager_token": "fresh-mgr"}

    resp_token = MagicMock()
    resp_token.status_code = 200
    resp_token.json.return_value = {"token": jwt_token}

    resp_ok = MagicMock()
    resp_ok.status_code = 200
    resp_ok.headers = {"X-Csrf-Token": "xsrf-fresh"}
    resp_ok.json.return_value = {"data": {"profile": "self-consumption"}}

    client.session.post = MagicMock(return_value=resp_login)
    client.session.get = MagicMock(side_effect=[resp_401, resp_token, resp_ok])

    data = client.get_status()
    assert data["data"]["profile"] == "self-consumption"
    assert client.manager_token == "fresh-mgr"
