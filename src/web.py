import logging
from typing import Any, Dict, Optional

from flask import Flask, jsonify, request

from enphase_client import (
    PROFILE_AI_OPTIMIZATION,
    PROFILE_FULL_BACKUP,
    PROFILE_SELF_CONSUMPTION,
    EnphaseCloudClient,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

PROFILE_DISPLAY_NAMES = {
    PROFILE_SELF_CONSUMPTION: "Self-Consumption",
    PROFILE_FULL_BACKUP: "Full Backup",
    PROFILE_AI_OPTIMIZATION: "AI Optimization",
    "cost_savings": "Savings",
    "expert": "Expert",
}

_client: Optional[EnphaseCloudClient] = None


def get_client() -> EnphaseCloudClient:
    global _client
    if _client is None:
        _client = EnphaseCloudClient()
    return _client


def _parse_reserve_arg() -> Optional[int]:
    raw = request.args.get("reserve")
    if raw is None and request.is_json:
        body = request.get_json(silent=True) or {}
        raw = body.get("reserve") or body.get("batteryBackupPercentage")
    if raw is None or raw == "":
        return None
    val = int(raw)
    if not 5 <= val <= 100:
        raise ValueError("reserve must be between 5 and 100")
    return val


def _format_status_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = payload.get("data") or {}
    profile = data.get("profile")
    dtg = data.get("dtgControl") or {}
    cfg = data.get("cfgControl") or {}
    return {
        "status": "ok",
        "timestamp": payload.get("timestamp"),
        "profile": profile,
        "profileDisplayName": PROFILE_DISPLAY_NAMES.get(profile, profile),
        "batteryBackupPercentage": data.get("batteryBackupPercentage"),
        "operationModeSubType": data.get("operationModeSubType"),
        "stormGuardState": data.get("stormGuardState"),
        "buybackExportPlan": data.get("buybackExportPlan"),
        "veryLowSoc": data.get("veryLowSoc"),
        "exportToGridEnabled": dtg.get("enabled"),
        "chargeFromGridEnabled": cfg.get("enabled"),
        "isBatteryChangePending": data.get("isBatteryChangePending"),
        "siteProfileStatus": data.get("siteProfileStatus"),
        "previousBatteryBackupPercentage": data.get("previousBatteryBackupPercentage"),
        "data": data,
    }


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({"status": "ok"}), 200


@app.route("/status", methods=["GET"])
def status():
    try:
        payload = get_client().get_status()
        return jsonify(_format_status_response(payload)), 200
    except Exception as exc:
        logger.exception("Failed to fetch Enphase battery profile status")
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route("/self-consumption", methods=["GET", "POST"])
def self_consumption():
    try:
        reserve = _parse_reserve_arg()
        result = get_client().set_self_consumption(reserve=reserve)
        return jsonify(result), 200
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception as exc:
        logger.exception("Failed to set Enphase profile to self-consumption")
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route("/full-backup", methods=["GET", "POST"])
def full_backup():
    try:
        result = get_client().set_full_backup()
        return jsonify(result), 200
    except Exception as exc:
        logger.exception("Failed to set Enphase profile to full-backup")
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route("/ai-optimization", methods=["GET", "POST"])
@app.route("/ai-optimisation", methods=["GET", "POST"])
def ai_optimization():
    try:
        reserve = _parse_reserve_arg()
        sub_type = request.args.get("sub_type")
        if sub_type is None and request.is_json:
            body = request.get_json(silent=True) or {}
            sub_type = body.get("operationModeSubType") or body.get("sub_type")
        result = get_client().set_ai_optimization(
            reserve=reserve,
            operation_mode_sub_type=sub_type,
        )
        return jsonify(result), 200
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception as exc:
        logger.exception("Failed to set Enphase profile to ai-optimization")
        return jsonify({"status": "error", "message": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
