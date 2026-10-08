import time
from flask import request, jsonify, abort
from security import require_ui_auth, require_api_key
import oauth_bridge

def register_oauth_routes(app):

    @app.route("/api/oauth/grants", methods=["GET"])
    @require_ui_auth
    def get_grants():
        return jsonify(oauth_bridge.list_grants())

    @app.route("/api/oauth/grants/<grant_id>", methods=["DELETE"])
    @require_ui_auth
    def revoke_grant(grant_id):
        oauth_bridge.revoke_grant(grant_id)
        return jsonify({"success": True})

    @app.route("/api/oauth/consent/approve", methods=["POST"])
    @require_ui_auth
    def approve_consent():
        client_name = request.json.get("client_name", "Unknown Client")
        state = request.json.get("state")
        
        if not state:
            return jsonify({"error": "state required"}), 400
            
        grant_id = oauth_bridge.create_grant(client_name)
        signed_token = oauth_bridge.sign_consent_response(grant_id, state)
        return jsonify({"success": True, "token": signed_token})

    # Vercelからのシステムコール用（UIログイン不要、APIキー必須）

    @app.route("/api/oauth/codes/redeem", methods=["POST"])
    @require_api_key
    def redeem_code():
        """認可コードの使用済み登録（リプレイ攻撃防止）。"""
        code_id = request.json.get("code_id")
        if not code_id:
            return jsonify({"error": "code_id required"}), 400
            
        if oauth_bridge.record_code_used(code_id):
            return jsonify({"success": True})
        else:
            return jsonify({"error": "Code already used or expired"}), 400

    @app.route("/api/oauth/grants/<grant_id>/refresh", methods=["POST"])
    @require_api_key
    def refresh_grant(grant_id):
        """リフレッシュトークン使用時の連携の有効性確認と利用日時更新。"""
        if oauth_bridge.update_grant_activity(grant_id):
            return jsonify({"success": True})
        else:
            return jsonify({"error": "Grant revoked or expired"}), 401
