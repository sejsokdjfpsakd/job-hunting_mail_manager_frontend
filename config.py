"""設定の読み込み（.env / 環境変数）。"""
import os
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _parse_env_file(path: str) -> dict:
    try:
        from dotenv import dotenv_values  # type: ignore
        return {k: v for k, v in dotenv_values(path).items() if v is not None}
    except ImportError:
        pass
    values = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                val = val.strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                    val = val[1:-1]
                values[key.strip()] = val
    except FileNotFoundError:
        pass
    return values


def is_dev_mode() -> bool:
    """ローカル開発専用モード。CGI(GATEWAY_INTERFACE有り)では常に無効。"""
    return os.environ.get("MAILMGR_DEV") == "1" and not os.environ.get("GATEWAY_INTERFACE")


class Settings:
    def __init__(self, env: dict | None = None):
        if env is None:
            env = dict(_parse_env_file(os.path.join(BASE_DIR, ".env")))
            for k, v in os.environ.items():  # 環境変数が優先（テスト・開発用）
                if k.startswith(("IMAP_", "APP_", "MCP_", "API_", "OAUTH_", "DATA_", "GRANT_", "RUN_",
                                 "SESSION_", "MAX_")):
                    env[k] = v
        g = env.get
        self.app_base_url = (g("APP_BASE_URL") or "http://localhost:8000/").rstrip("/") + "/"
        parsed = urlparse(self.app_base_url)
        self.app_origin = f"{parsed.scheme}://{parsed.netloc}"
        self.rp_id = parsed.hostname or "localhost"
        self.mcp_public_url = (g("MCP_PUBLIC_URL") or "").rstrip("/")
        self.imap_host = g("IMAP_HOST", "")
        self.imap_port = int(g("IMAP_PORT", "143") or 143)
        self.imap_user = g("IMAP_USER", "")
        self.imap_password = g("IMAP_PASSWORD", "")
        self.imap_mock = g("IMAP_MOCK", "") == "1"
        self.api_key = g("API_KEY", "")
        self.bridge_secret = g("OAUTH_BRIDGE_SECRET", "")
        data_dir = g("DATA_DIR", "data")
        self.data_dir = data_dir if os.path.isabs(data_dir) else os.path.join(BASE_DIR, data_dir)
        self.session_idle_seconds = int(g("SESSION_IDLE_MINUTES", "30")) * 60
        self.session_max_seconds = int(g("SESSION_MAX_HOURS", "12")) * 3600
        self.grant_idle_seconds = int(g("GRANT_IDLE_DAYS", "30")) * 86400
        self.run_budget_seconds = float(g("RUN_TIME_BUDGET_SECONDS", "20"))
        self.cookie_secure = parsed.scheme == "https"

    def problems(self) -> list[str]:
        out = []
        if len(self.api_key) < 32:
            out.append("API_KEY は32文字以上にしてください（manage.py gen-secrets）")
        if len(self.bridge_secret) < 32:
            out.append("OAUTH_BRIDGE_SECRET は32文字以上にしてください")
        if not self.imap_mock and not (self.imap_host and self.imap_user and self.imap_password):
            out.append("IMAP_HOST / IMAP_USER / IMAP_PASSWORD が未設定です")
        return out


_cached: Settings | None = None


def get_settings() -> Settings:
    global _cached
    if _cached is None:
        _cached = Settings()
    return _cached


def set_settings(s: Settings | None) -> None:
    """テスト用: 設定を差し替える（Noneで再読込）。"""
    global _cached
    _cached = s

