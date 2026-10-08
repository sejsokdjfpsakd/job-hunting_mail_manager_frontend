import os
import time
import uuid
from flask import Flask, request, jsonify, abort, make_response
from config import get_settings
from security import create_session, destroy_session, require_ui_auth, require_api_key, require_oauth_access_token, require_auth
import passkey
import oauth_bridge

from storage import JsonStore

from api_imap import register_imap_routes
from api_rules import register_rules_routes
from api_oauth import register_oauth_routes

app = Flask(__name__)
register_imap_routes(app)
register_rules_routes(app)
register_oauth_routes(app)

# setup session challenge store for WebAuthn
challenges_store = JsonStore("auth_challenges.json", {})

def _set_cookie(resp, name, value, max_age):
    settings = get_settings()
    resp.set_cookie(
        name,
        value,
        max_age=max_age,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="Strict"
    )

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "problems": get_settings().problems()})

# --- UI Auth ---

@app.route("/api/auth/me")
@require_ui_auth
def auth_me():
    return jsonify({"authenticated": True})

@app.route("/api/auth/logout", methods=["POST"])
@require_ui_auth
def logout():
    token = request.cookies.get("session_id")
    destroy_session(token)
    resp = jsonify({"success": True})
    _set_cookie(resp, "session_id", "", 0)
    return resp

@app.route("/api/auth/passkey/login/options", methods=["POST"])
def login_options():
    try:
        options = passkey.start_authentication()
        # Save challenge temporarily
        session_id = str(uuid.uuid4())
        def _save(data):
            data[session_id] = {"challenge": options["challenge"], "time": time.time()}
        challenges_store.update(_save)
        
        resp = jsonify(options)
        _set_cookie(resp, "auth_session", session_id, 300)
        return resp
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/auth/passkey/login/verify", methods=["POST"])
def login_verify():
    auth_session = request.cookies.get("auth_session")
    if not auth_session:
        return jsonify({"error": "No auth session"}), 400
        
    def _get_and_del(data):
        if auth_session in data:
            c = data[auth_session]["challenge"]
            del data[auth_session]
            return c
        return None
    challenge = challenges_store.update(_get_and_del)
    
    if not challenge:
        return jsonify({"error": "Invalid or expired session"}), 400
        
    if passkey.verify_authentication(request.json, challenge):
        session_token = create_session()
        resp = jsonify({"success": True, "csrf_token": session_token})
        _set_cookie(resp, "session_id", session_token, get_settings().session_max_seconds)
        _set_cookie(resp, "auth_session", "", 0)
        return resp
    else:
        return jsonify({"error": "Authentication failed"}), 401

@app.route("/api/auth/passkeys", methods=["GET"])
@require_ui_auth
def get_passkeys():
    return jsonify(passkey.get_all_passkeys())

@app.route("/api/auth/passkeys/<cred_id>", methods=["DELETE"])
@require_ui_auth
def delete_passkey(cred_id):
    try:
        passkey.delete_passkey(cred_id)
        return jsonify({"success": True})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

# Setup tool for passkeys (requires CLI run for first time)
setup_tokens_store = JsonStore("setup_tokens.json", {})

@app.route("/api/auth/passkey/register/options", methods=["POST"])
def register_options():
    # Only allow if authenticated OR has a valid setup token
    setup_token = request.json.get("setup_token")
    if setup_token:
        def _check(data):
            if setup_token in data and time.time() - data[setup_token] < 900:
                del data[setup_token]
                return True
            return False
        if not setup_tokens_store.update(_check):
            return jsonify({"error": "Invalid or expired setup token"}), 401
    else:
        # Require normal auth
        token = request.cookies.get("session_id")
        from security import verify_session
        if not token or not verify_session(token):
            return jsonify({"error": "Unauthorized"}), 401
            
    try:
        options = passkey.start_registration()
        session_id = str(uuid.uuid4())
        def _save(data):
            data[session_id] = {"challenge": options["challenge"], "time": time.time()}
        challenges_store.update(_save)
        
        resp = jsonify(options)
        _set_cookie(resp, "auth_session", session_id, 300)
        return resp
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/auth/passkey/register/verify", methods=["POST"])
def register_verify():
    auth_session = request.cookies.get("auth_session")
    if not auth_session:
        return jsonify({"error": "No auth session"}), 400
        
    def _get_and_del(data):
        if auth_session in data:
            c = data[auth_session]["challenge"]
            del data[auth_session]
            return c
        return None
    challenge = challenges_store.update(_get_and_del)
    
    if not challenge:
        return jsonify({"error": "Invalid session"}), 400
        
    try:
        res = passkey.verify_registration(request.json, challenge)
        return jsonify({"success": True, "id": res["id"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

