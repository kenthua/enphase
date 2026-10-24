import base64
import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

ENLIGHTEN_BASE_URL = "https://enlighten.enphaseenergy.com"
BATTERY_UI_ORIGIN = "https://battery-profile-ui.enphaseenergy.com"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

PROFILE_SELF_CONSUMPTION = "self-consumption"
PROFILE_FULL_BACKUP = "backup_only"
PROFILE_AI_OPTIMIZATION = "ai_optimisation"

DEFAULT_RESERVE_BY_PROFILE = {
    PROFILE_SELF_CONSUMPTION: 20,
    PROFILE_FULL_BACKUP: 100,
    PROFILE_AI_OPTIMIZATION: 10,
}


def decode_jwt_claims(jwt_token: str) -> Dict[str, Any]:
    """Decode the payload claims from a JWT without requiring external crypto libs."""
    parts = jwt_token.split(".")
    if len(parts) < 2:
        raise ValueError("Invalid JWT token format")
    payload_b64 = parts[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    decoded = base64.urlsafe_b64decode(payload_b64)
    return json.loads(decoded)


class EnphaseCloudClient:
    """Direct HTTP client for the Enphase Enlighten batteryConfig Cloud API."""

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        site_id: Optional[str] = None,
        user_id: Optional[str] = None,
        backup_reserve: Optional[int] = None,
        cache_file: Optional[str] = "/tmp/enphase_session_cache.json",
        timeout: int = 20,
    ) -> None:
        self.username = username if username is not None else os.environ.get("USERNAME")
        self.password = password if password is not None else os.environ.get("PASSWORD")
        self.site_id = site_id if site_id is not None else os.environ.get("SITE_ID")
        self.user_id = user_id if user_id is not None else os.environ.get("USER_ID")
        if backup_reserve is not None:
            self.backup_reserve = int(backup_reserve)
        elif os.environ.get("BACKUP_RESERVE"):
            self.backup_reserve = int(os.environ["BACKUP_RESERVE"])
        else:
            self.backup_reserve = None

        self.cache_file = cache_file
        self.timeout = timeout
        self._lock = threading.Lock()

        self.session = self._build_session()
        self.jwt_token: Optional[str] = None
        self.manager_token: Optional[str] = None
        self.jwt_exp: Optional[int] = None

        self._load_session_cache()

    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[502, 503, 504],
            allowed_methods=["GET", "POST", "PUT"],
        )
        session.mount("https://", HTTPAdapter(max_retries=retry))
        session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
        return session

    def _validate_credentials(self) -> None:
        missing = []
        if not self.username:
            missing.append("USERNAME")
        if not self.password:
            missing.append("PASSWORD")
        if not self.site_id:
            missing.append("SITE_ID")
        if missing:
            raise ValueError(f"Missing required Enphase configuration: {', '.join(missing)}")

    def _load_session_cache(self) -> bool:
        if not self.cache_file or not os.path.exists(self.cache_file):
            return False
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                cache = json.load(f)
            self.session.cookies.update(cache.get("cookies", {}))
            self.jwt_token = cache.get("jwt_token")
            self.manager_token = cache.get("manager_token")
            self.user_id = self.user_id or cache.get("user_id")
            self.jwt_exp = cache.get("jwt_exp")
            return bool(self.jwt_token and self.user_id)
        except Exception as exc:
            logger.warning("Failed to load session cache from %s: %s", self.cache_file, exc)
            return False

    def _save_session_cache(self) -> None:
        if not self.cache_file:
            return
        try:
            fd = os.open(self.cache_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "cookies": self.session.cookies.get_dict(),
                        "jwt_token": self.jwt_token,
                        "manager_token": self.manager_token,
                        "user_id": self.user_id,
                        "jwt_exp": self.jwt_exp,
                    },
                    f,
                )
        except Exception as exc:
            logger.warning("Failed to write session cache to %s: %s", self.cache_file, exc)

    def _is_authenticated(self) -> bool:
        if not self.jwt_token or not self.user_id:
            return False
        if self.jwt_exp and time.time() >= (self.jwt_exp - 60):
            return False
        return True

    def login(self) -> None:
        """Authenticate against Enphase Enlighten and fetch the e-auth-token JWT."""
        self._validate_credentials()
        self.session.cookies.clear()

        login_url = f"{ENLIGHTEN_BASE_URL}/login/login.json"
        r_login = self.session.post(
            login_url,
            data={"user[email]": self.username, "user[password]": self.password},
            timeout=self.timeout,
        )
        r_login.raise_for_status()
        login_data = r_login.json()

        token_url = f"{ENLIGHTEN_BASE_URL}/users/self/token"
        r_token = self.session.get(token_url, timeout=self.timeout)
        r_token.raise_for_status()
        token_data = r_token.json()

        jwt_token = token_data.get("token")
        if not jwt_token:
            raise RuntimeError("Enphase /users/self/token response did not include a token")

        claims = decode_jwt_claims(jwt_token)
        extracted_uid = (
            claims.get("enl_uid")
            or claims.get("user_id")
            or claims.get("sub")
            or login_data.get("user_id")
        )
        if not extracted_uid and not self.user_id:
            raise RuntimeError("Unable to determine Enphase user_id from JWT claims")

        self.jwt_token = jwt_token
        self.jwt_exp = claims.get("exp")
        if extracted_uid:
            self.user_id = str(extracted_uid)
        self.manager_token = (
            login_data.get("manager_token")
            or self.session.cookies.get("enlighten_manager_token_production")
            or jwt_token
        )
        self._save_session_cache()

    def _profile_url(self) -> str:
        return (
            f"{ENLIGHTEN_BASE_URL}/service/batteryConfig/api/v1/profile/"
            f"{self.site_id}?source=enho&userId={self.user_id}"
        )

    def _base_headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Origin": BATTERY_UI_ORIGIN,
            "Referer": f"{BATTERY_UI_ORIGIN}/",
            "e-auth-token": self.jwt_token or "",
            "Authorization": f"Bearer {self.manager_token or self.jwt_token or ''}",
            "Username": str(self.user_id or ""),
        }

    def _fetch_profile_with_xsrf(self) -> tuple[Dict[str, Any], Optional[str]]:
        if not self._is_authenticated():
            self.login()

        resp = self.session.get(
            self._profile_url(),
            headers=self._base_headers(),
            timeout=self.timeout,
        )
        if resp.status_code in (401, 403):
            logger.info("Session expired (HTTP %s); re-authenticating with Enphase Cloud", resp.status_code)
            self.login()
            resp = self.session.get(
                self._profile_url(),
                headers=self._base_headers(),
                timeout=self.timeout,
            )

        resp.raise_for_status()
        xsrf_token = (
            resp.headers.get("X-Csrf-Token")
            or resp.headers.get("x-csrf-token")
            or self.session.cookies.get("BP-XSRF-Token")
        )
        self._save_session_cache()
        return resp.json(), xsrf_token

    def get_status(self) -> Dict[str, Any]:
        """Return the current battery profile configuration from Enphase Cloud."""
        with self._lock:
            payload, _ = self._fetch_profile_with_xsrf()
            return payload

    def _resolve_reserve_percentage(
        self,
        profile: str,
        current_data: Dict[str, Any],
        explicit_reserve: Optional[int] = None,
    ) -> int:
        if profile == PROFILE_FULL_BACKUP:
            return int(explicit_reserve) if explicit_reserve is not None else 100

        if explicit_reserve is not None:
            return int(explicit_reserve)

        if self.backup_reserve is not None:
            return int(self.backup_reserve)

        prev_map = current_data.get("previousBatteryBackupPercentage") or {}
        if profile in prev_map and prev_map[profile] is not None:
            return int(prev_map[profile])

        return DEFAULT_RESERVE_BY_PROFILE.get(profile, 20)

    def set_profile(
        self,
        profile: str,
        battery_backup_percentage: Optional[int] = None,
        operation_mode_sub_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Switch the Enphase battery profile via the Cloud batteryConfig API."""
        with self._lock:
            status_payload, xsrf_token = self._fetch_profile_with_xsrf()
            current_data = status_payload.get("data") or {}

            if not xsrf_token:
                raise RuntimeError("Failed to obtain BP-XSRF-Token / X-Csrf-Token from Enphase Cloud")

            reserve = self._resolve_reserve_percentage(
                profile=profile,
                current_data=current_data,
                explicit_reserve=battery_backup_percentage,
            )

            body: Dict[str, Any] = {
                "profile": profile,
                "batteryBackupPercentage": reserve,
            }
            if profile == PROFILE_AI_OPTIMIZATION:
                body["operationModeSubType"] = (
                    operation_mode_sub_type
                    or current_data.get("operationModeSubType")
                    or "prioritize-energy"
                )

            put_headers = self._base_headers()
            put_headers["X-XSRF-Token"] = xsrf_token
            put_headers["Content-Type"] = "application/json"

            resp = self.session.put(
                self._profile_url(),
                headers=put_headers,
                json=body,
                timeout=self.timeout,
            )
            if resp.status_code in (401, 403):
                logger.info("PUT returned HTTP %s; re-authenticating and retrying", resp.status_code)
                self.login()
                status_payload, xsrf_token = self._fetch_profile_with_xsrf()
                if not xsrf_token:
                    raise RuntimeError("Failed to obtain BP-XSRF-Token on retry")
                put_headers = self._base_headers()
                put_headers["X-XSRF-Token"] = xsrf_token
                put_headers["Content-Type"] = "application/json"
                resp = self.session.put(
                    self._profile_url(),
                    headers=put_headers,
                    json=body,
                    timeout=self.timeout,
                )

            resp.raise_for_status()
            self._save_session_cache()
            result = resp.json() if resp.content else {"message": "success"}
            return {
                "status": "ok",
                "profile": profile,
                "batteryBackupPercentage": reserve,
                "response": result,
            }

    def set_self_consumption(self, reserve: Optional[int] = None) -> Dict[str, Any]:
        return self.set_profile(PROFILE_SELF_CONSUMPTION, battery_backup_percentage=reserve)

    def set_full_backup(self) -> Dict[str, Any]:
        return self.set_profile(PROFILE_FULL_BACKUP, battery_backup_percentage=100)

    def set_ai_optimization(
        self,
        reserve: Optional[int] = None,
        operation_mode_sub_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.set_profile(
            PROFILE_AI_OPTIMIZATION,
            battery_backup_percentage=reserve,
            operation_mode_sub_type=operation_mode_sub_type,
        )
