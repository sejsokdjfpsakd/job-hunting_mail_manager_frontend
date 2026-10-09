import hashlib
import secrets
import time
from flask import request, abort, make_response
from functools import wraps
from config import get_settings, is_dev_mode
from storage import JsonStore

sessions_store = JsonStore("sessions.json", {})


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session() -> str:
    """新しいセッションを作成し、セッショントークンを返す。"""
    token = secrets.token_urlsafe(32)
    token_hash = hash_token(token)
    now = time.time()
    
    def _add(data):
        data[token_hash] = {
            "created_at": now,
            "last_seen": now
        }
    sessions_store.update(_add)
    return token


def verify_session(token: str) -> bool:
    """セッションの有効性を確認し、last_seenを更新する。"""
    if not token:
        return False
        
    token_hash = hash_token(token)
    settings = get_settings()
    now = time.time()
    
    def _verify(data):
        if token_hash not in data:
            return False
            
        session = data[token_hash]
        if now - session["last_seen"] > settings.session_idle_seconds:
            del data[token_hash]
            return False
            
        if now - session["created_at"] > settings.session_max_seconds:
            del data[token_hash]
            return False
            
        session["last_seen"] = now
        return True
        
    return sessions_store.update(_verify)


def destroy_session(token: str):
    """セッションを破棄する。"""
    if not token:
        return
        
    token_hash = hash_token(token)
    def _delete(data):
        if token_hash in data:
            del data[token_hash]
    sessions_store.update(_delete)


def require_ui_auth(f):
    """UIログインが必要なエンドポイントのデコレータ。"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        settings = get_settings()
        
        # ローカル専用 ログイン省略モード
        if is_dev_mode() and request.headers.get("X-Dev-Auth") == "1":
            return f(*args, **kwargs)
            
        token = request.cookies.get("session_id")
        if not token or not verify_session(token):
            abort(401)
            
        # CSRFチェック (GET以外)
        if request.method not in ["GET", "HEAD", "OPTIONS"]:
            csrf_token = request.headers.get("X-CSRF-Token")
            if not csrf_token or csrf_token != token:
                abort(403, "CSRF token missing or invalid")
                
        return f(*args, **kwargs)
    return decorated_function


def require_api_key(f):
    """MCPサーバーからのAPI呼び出し用（APIキー必須）。"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get("Authorization")
        if not api_key:
            abort(401, "API Key missing")
            
        if api_key.startswith("Bearer "):
            api_key = api_key[len("Bearer "):]
            
        settings = get_settings()
        if not settings.api_key or not secrets.compare_digest(api_key, settings.api_key):
            abort(401, "Invalid API Key")
            
        return f(*args, **kwargs)
    return decorated_function


def require_oauth_access_token(f):
    """OAuthアクセストークンの検証を必要とする場合（MCPツール用）。
    Vercelから送信される APIキー ＋ アクセストークン の両方を検証する。
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 1. APIキー検証
        require_api_key(lambda: None)()
        
        # 2. アクセストークン検証
        mcp_token = request.headers.get("X-MCP-Access-Token")
        if not mcp_token:
            abort(401, "X-MCP-Access-Token missing")
            
        settings = get_settings()
        
        # シングルユーザーモード対応: APIキー自体をアクセストークンとして使ってきた場合は特別に許可
        if mcp_token == settings.api_key:
            request.oauth_grant_id = "single_user_grant"
            return f(*args, **kwargs)
            
        from oauth_bridge import verify_access_token
        if is_dev_mode() and (mcp_token == "dev_token" or not mcp_token):
            request.oauth_grant_id = "dev_grant"
            return f(*args, **kwargs)

        grant_id = verify_access_token(mcp_token)
        if not grant_id:
            abort(401, "Invalid or expired MCP Access Token")
            
        # grant_id を request オブジェクトに保存しておく
        request.oauth_grant_id = grant_id
        return f(*args, **kwargs)
    return decorated_function
def require_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Allow MCP token if present
        if request.headers.get("Authorization") and request.headers.get("X-MCP-Access-Token"):
            return require_oauth_access_token(f)(*args, **kwargs)
        # Otherwise, require UI session
        return require_ui_auth(f)(*args, **kwargs)
    return decorated_function

