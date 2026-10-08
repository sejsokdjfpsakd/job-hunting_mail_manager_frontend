import os
import sys

# 開発用環境変数を自動設定
os.environ.setdefault("MAILMGR_DEV", "1")
os.environ.setdefault("IMAP_MOCK", "1")
os.environ.setdefault("API_KEY", "dev-api-key-for-local-testing-only-1234567890")
os.environ.setdefault("OAUTH_BRIDGE_SECRET", "dev-bridge-secret-for-local-testing-only-1234567890")
os.environ.setdefault("APP_BASE_URL", "http://localhost:8000/")

from api_server import app
from config import get_settings
from mock_imap_client import reset_mock
from werkzeug.middleware.dispatcher import DispatcherMiddleware

# `/api.cgi` から始まるリクエストも同じ Flask app で処理できるようにマウント
application = DispatcherMiddleware(app, {
    "/api.cgi": app
})

if __name__ == "__main__":
    from werkzeug.serving import run_simple
    
    settings = get_settings()
    reset_mock()
    print("=" * 60)
    print("🚀 Rental Server (開発・モック用サーバー) を起動します")
    print("=" * 60)
    print(f"・URL: http://localhost:8000/")
    print(f"・IMAPモード: モック (IMAP_MOCK=1) ※テスト用メール自動生成済み")
    print(f"・APIキー: {settings.api_key}")
    print(f"・OAuth Bridge Secret: {settings.bridge_secret}")
    print("=" * 60)
    print("終了するには Ctrl+C を押してください。\n")
    
    run_simple("127.0.0.1", 8000, application, use_reloader=True, use_debugger=True)

