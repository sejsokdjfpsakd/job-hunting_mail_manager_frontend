from flask import request, jsonify
from security import require_auth
import rules
from imap_client import open_session

def register_rules_routes(app):

    @app.route("/api/rules", methods=["GET"])
    @require_auth
    def get_rules():
        return jsonify(rules.list_rules())

    @app.route("/api/rules", methods=["POST"])
    @require_auth
    def create_rule():
        rule_data = request.json
        if not rule_data:
            return jsonify({"error": "JSON body required"}), 400
        try:
            rule = rules.create_rule(rule_data)
            return jsonify({"success": True, "rule": rule})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/rules/<rule_id>", methods=["PUT"])
    @require_auth
    def update_rule(rule_id):
        updates = request.json
        if not updates:
            return jsonify({"error": "JSON body required"}), 400
        try:
            rule, rescan = rules.update_rule(rule_id, updates)
            return jsonify({"success": True, "rule": rule, "rescan": rescan})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/rules/<rule_id>", methods=["DELETE"])
    @require_auth
    def delete_rule(rule_id):
        try:
            ok = rules.delete_rule(rule_id)
            if ok:
                return jsonify({"success": True})
            return jsonify({"error": "Not found"}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/rules/preview", methods=["POST"])
    @require_auth
    def api_preview_rule():
        condition = request.json.get("condition")
        if not condition:
            return jsonify({"error": "condition required"}), 400
        try:
            with open_session() as s:
                res = rules.preview(s, condition)
            return jsonify(res)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/rules/run", methods=["POST"])
    @require_auth
    def run_rules():
        dry_run = request.json.get("dry_run", False)
        rule_id = request.json.get("rule_id")
        try:
            with open_session() as s:
                res = rules.run_rules(s, rule_id=rule_id, dry_run=dry_run)
            return jsonify({"success": True, "result": res})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
