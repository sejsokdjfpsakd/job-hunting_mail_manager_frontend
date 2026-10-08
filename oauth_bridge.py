import time
import secrets
import hashlib
from config import get_settings
from storage import JsonStore
import jwt_lite

grants_store = JsonStore("grants.json", {})
codes_store = JsonStore("used_codes.json", {})


def _prune_codes(data: dict):
    now = time.time()
    # Remove codes older than 5 minutes
    expired = [k for k, v in data.items() if now - v > 300]
    for k in expired:
        del data[k]


def record_code_used(code_id: str) -> bool:
    """認可コードが使用済みかをチェックし、登録する。"""
    if not code_id:
        return False
        
    code_hash = hashlib.sha256(code_id.encode("utf-8")).hexdigest()
    now = time.time()
    
    def _record(data):
        _prune_codes(data)
        if code_hash in data:
            return False # Already used!
        data[code_hash] = now
        return True
        
    return codes_store.update(_record)


def create_grant(client_name: str) -> str:
    """アプリへの新しい連携を許可し、grant_idを返す。"""
    grant_id = secrets.token_urlsafe(32)
    now = time.time()
    
    def _add(data):
        data[grant_id] = {
            "name": client_name,
            "created_at": now,
            "last_seen": now,
        }
    grants_store.update(_add)
    return grant_id


def revoke_grant(grant_id: str):
    """連携を解除する。"""
    def _revoke(data):
        if grant_id in data:
            del data[grant_id]
    grants_store.update(_revoke)


def list_grants() -> list:
    """有効な連携の一覧を返す。期限切れは自動削除。"""
    settings = get_settings()
    now = time.time()
    
    def _list(data):
        expired = [k for k, v in data.items() if now - v["last_seen"] > settings.grant_idle_seconds]
        for k in expired:
            del data[k]
        
        # Sort by last_seen desc
        items = []
        for k, v in data.items():
            items.append({
                "id": k,
                "name": v["name"],
                "created_at": v["created_at"],
                "last_seen": v["last_seen"]
            })
        return items
        
    return grants_store.update(_list)


def update_grant_activity(grant_id: str) -> bool:
    """連携の利用日時を更新する。"""
    settings = get_settings()
    now = time.time()
    
    def _update(data):
        if grant_id not in data:
            return False
        grant = data[grant_id]
        if now - grant["last_seen"] > settings.grant_idle_seconds:
            del data[grant_id]
            return False
        grant["last_seen"] = now
        return True
        
    return grants_store.update(_update)


def verify_access_token(token: str) -> str | None:
    """アクセストークンを検証し、対応する grant_id を返す。
    無効、期限切れ、または対応する連携が失効している場合は None。
    """
    settings = get_settings()
    try:
        payload = jwt_lite.verify(token, secret=settings.bridge_secret, aud="mcp_server")
        grant_id = payload.get("sub")
        if not grant_id:
            return None
            
        if update_grant_activity(grant_id):
            return grant_id
        return None
    except jwt_lite.JWTError:
        return None


def sign_consent_response(grant_id: str, state: str) -> str:
    """同意結果を Vercel に送るための署名付きトークンを生成する。"""
    settings = get_settings()
    payload = {
        "grant_id": grant_id,
        "state": state
    }
    # Vercel's /oauth/callback expects this token
    return jwt_lite.sign(payload, secret=settings.bridge_secret, aud="oauth_callback", ttl=300)

