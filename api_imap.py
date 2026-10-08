from flask import request, jsonify, abort
from security import require_auth
from imap_client import get_imap_client
import rules

def register_imap_routes(app):

    @app.route("/api/folders", methods=["GET"])
    @require_auth
    def get_folders():
        try:
            client = get_imap_client()
            return jsonify(client.get_folders())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/folders", methods=["POST"])
    @require_auth
    def create_folder():
        name = request.json.get("name")
        if not name:
            return jsonify({"error": "Name required"}), 400
        try:
            client = get_imap_client()
            client.create_folder(name)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/folders", methods=["PATCH"])
    @require_auth
    def rename_folder():
        old_name = request.json.get("from")
        new_name = request.json.get("to")
        if not old_name or not new_name:
            return jsonify({"error": "from and to required"}), 400
        try:
            client = get_imap_client()
            client.rename_folder(old_name, new_name)
            
            # ルールの移動先も自動更新する
            rules.on_folder_renamed(old_name, new_name)
            
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/folders", methods=["DELETE"])
    @require_auth
    def delete_folder():
        name = request.args.get("name")
        if not name:
            return jsonify({"error": "name parameter required"}), 400
        try:
            client = get_imap_client()
            client.delete_folder(name)
            rules.on_folder_deleted(name)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/emails", methods=["GET"])
    @require_auth
    def get_emails():
        folder = request.args.get("folder", "INBOX")
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
        unread_only = request.args.get("unread") == "true"
        
        # filters
        subject = request.args.get("subject")
        from_address = request.args.get("from")
        to_address = request.args.get("to")
        
        # 複雑な条件ツリーは JSON 文字列として "q" パラメータで受け取る
        q_json = request.args.get("q")
        condition = None
        if q_json:
            import json
            try:
                condition = json.loads(q_json)
            except:
                return jsonify({"error": "Invalid q JSON"}), 400
                
        try:
            client = get_imap_client()
            emails = client.get_recent_emails(
                folder=folder,
                limit=limit,
                offset=offset,
                unread_only=unread_only,
                subject=subject,
                from_address=from_address,
                to_address=to_address,
                condition_tree=condition
            )
            return jsonify(emails)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/emails/<uid>", methods=["GET"])
    @require_auth
    def get_email(uid):
        folder = request.args.get("folder", "INBOX")
        max_chars = int(request.args.get("max_chars", 20000))
        try:
            client = get_imap_client()
            email = client.get_email(uid, folder=folder, max_chars=max_chars)
            if not email:
                return jsonify({"error": "Not found"}), 404
            return jsonify(email)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/emails/move", methods=["POST"])
    @require_auth
    def move_email():
        uid = request.json.get("uid")
        uids = request.json.get("uids")
        target = request.json.get("target_folder")
        source = request.json.get("source_folder", "INBOX")
        
        if not target:
            return jsonify({"error": "target_folder required"}), 400
            
        try:
            client = get_imap_client()
            if uid:
                client.move_email(uid, target, source)
            elif uids:
                # 複数移動
                for u in uids:
                    client.move_email(u, target, source)
            else:
                return jsonify({"error": "uid or uids required"}), 400
                
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

