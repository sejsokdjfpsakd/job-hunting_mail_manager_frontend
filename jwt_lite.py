"""標準ライブラリだけで実装した最小限のJWT(HS256)。Vercel側(jose)と互換。"""
import base64
import hashlib
import hmac
import json
import time


class JWTError(Exception):
    pass


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign(payload: dict, secret: str, aud: str, ttl: int) -> str:
    now = int(time.time())
    body = dict(payload)
    body.update({"aud": aud, "iat": now, "exp": now + int(ttl)})
    head = _b64e(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    pl = _b64e(json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode())
    sig = hmac.new(secret.encode(), f"{head}.{pl}".encode(), hashlib.sha256).digest()
    return f"{head}.{pl}.{_b64e(sig)}"


def verify(token: str, secret: str, aud: str, leeway: int = 5) -> dict:
    try:
        head_s, pl_s, sig_s = token.split(".")
        header = json.loads(_b64d(head_s))
        if header.get("alg") != "HS256":
            raise JWTError("alg")
        expected = hmac.new(secret.encode(), f"{head_s}.{pl_s}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64d(sig_s)):
            raise JWTError("signature")
        payload = json.loads(_b64d(pl_s))
    except JWTError:
        raise
    except Exception as exc:
        raise JWTError("malformed") from exc
    if payload.get("aud") != aud:
        raise JWTError("aud")
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or time.time() > exp + leeway:
        raise JWTError("expired")
    return payload

