import json
import base64
from typing import Optional, Dict
from config import get_settings
from storage import JsonStore

try:
    from webauthn import (
        generate_registration_options,
        verify_registration_response,
        generate_authentication_options,
        verify_authentication_response,
        options_to_json,
        base64url_to_bytes
    )
    from webauthn.helpers.structs import (
        RegistrationCredential,
        AuthenticationCredential,
        AuthenticatorSelectionCriteria,
        UserVerificationRequirement,
        ResidentKeyRequirement
    )
    HAS_WEBAUTHN = True
except ImportError:
    HAS_WEBAUTHN = False

passkeys_store = JsonStore("passkeys.json", {})


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def is_supported() -> bool:
    return HAS_WEBAUTHN


def get_all_passkeys() -> list[dict]:
    def _read(data):
        return [{"id": k, "name": v["name"], "created_at": v.get("created_at", 0)} for k, v in data.items()]
    return passkeys_store.update(_read)


def delete_passkey(credential_id: str) -> bool:
    def _del(data):
        if credential_id in data:
            if len(data) <= 1:
                raise ValueError("最後のパスキーは削除できません")
            del data[credential_id]
            return True
        return False
    return passkeys_store.update(_del)


def start_registration(user_id: str = "admin", name: str = "Admin") -> dict:
    if not HAS_WEBAUTHN:
        raise RuntimeError("webauthn library not installed")
        
    settings = get_settings()
    options = generate_registration_options(
        rp_id=settings.rp_id,
        rp_name="Mail Manager",
        user_id=user_id.encode("utf-8"),
        user_name=name,
        user_display_name=name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[],
    )
    return json.loads(options_to_json(options))


def verify_registration(response_json: dict, expected_challenge: str) -> dict:
    if not HAS_WEBAUTHN:
        raise RuntimeError("webauthn library not installed")
        
    settings = get_settings()
    credential = verify_registration_response(
        credential=response_json,
        expected_challenge=base64url_to_bytes(expected_challenge),
        expected_origin=settings.app_origin,
        expected_rp_id=settings.rp_id,
        require_user_verification=True
    )
    
    cred_id = _b64e(credential.credential_id)
    public_key = _b64e(credential.credential_public_key)
    
    def _save(data):
        data[cred_id] = {
            "name": f"Passkey {len(data) + 1}",
            "public_key": public_key,
            "sign_count": credential.sign_count
        }
    passkeys_store.update(_save)
    
    return {"id": cred_id}


def start_authentication() -> dict:
    if not HAS_WEBAUTHN:
        raise RuntimeError("webauthn library not installed")
        
    settings = get_settings()
    options = generate_authentication_options(
        rp_id=settings.rp_id,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return json.loads(options_to_json(options))


def verify_authentication(response_json: dict, expected_challenge: str) -> bool:
    if not HAS_WEBAUTHN:
        raise RuntimeError("webauthn library not installed")
        
    settings = get_settings()
    
    def _get_key(data):
        cred_id = response_json.get("id")
        if not cred_id or cred_id not in data:
            return None
        return cred_id, data[cred_id]
        
    res = passkeys_store.update(_get_key)
    if not res:
        return False
        
    cred_id, stored_cred = res
    
    try:
        credential = verify_authentication_response(
            credential=response_json,
            expected_challenge=base64url_to_bytes(expected_challenge),
            expected_origin=settings.app_origin,
            expected_rp_id=settings.rp_id,
            credential_public_key=base64url_to_bytes(stored_cred["public_key"]),
            credential_current_sign_count=stored_cred["sign_count"],
            require_user_verification=True
        )
    except Exception:
        return False
        
    def _update_count(data):
        if cred_id in data:
            data[cred_id]["sign_count"] = credential.new_sign_count
    passkeys_store.update(_update_count)
    
    return True
