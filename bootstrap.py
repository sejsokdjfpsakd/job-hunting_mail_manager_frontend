"""CGI/CLI 共通の起動処理。packages/ をパスに追加し、FlaskアプリをCGIとして実行する。"""
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGES_DIR = os.path.join(BASE_DIR, "packages")

for _p in (PACKAGES_DIR, BASE_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _fail(status: str, message: str) -> None:
    body = json.dumps({"ok": False, "error": message}, ensure_ascii=False)
    sys.stdout.write("Status: %s\r\nContent-Type: application/json; charset=utf-8\r\n"
                     "Cache-Control: no-store\r\n\r\n%s" % (status, body))


def run_cgi() -> None:
    from wsgiref.handlers import CGIHandler
    try:
        from api_server import app
    except Exception:  # 詳細は外部に出さない
        import traceback
        traceback.print_exc(file=sys.stderr)
        _fail("500 Internal Server Error", "server_error")
        return
    CGIHandler().run(app)
