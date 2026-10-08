"""自動振り分けルールの保存・検証・実行。

- 通常実行（差分）: ルールごとの「判定済みUID位置」より新しいメールだけを判定（メールには何も書き込まない）。
- 全件再判定: ルールの新規作成・編集・再有効化時、UIDVALIDITY変更時。INBOX＋全ラベルフォルダ（特殊フォルダ・自分の移動先を除く）が対象。
  複数ルールに一致するメールは常に最優先ルールのフォルダに入る（優先度の高いルールに一致するメールは除外して判定）。
  時間制限（CGI対策）で途中終了しても、次回実行で続きから再開する（移動済みは再検索で自然に除外される）。
"""
import secrets
import time

from imap_client import MailError, is_inbox, special_kind, validate_folder_name
from search_builder import ConditionError, validate_condition
from storage import JsonStore, file_lock, now

_rules = JsonStore("rules.json", {"rules": []})
_state = JsonStore("rule_state.json", {})

BATCH = 200


# ------------------------------------------------------------ CRUD
def list_rules() -> list[dict]:
    rules = _rules.read()["rules"]
    return sorted(rules, key=lambda r: (r["priority"], r["created_at"]))


def get_rule(rule_id: str) -> dict | None:
    return next((r for r in _rules.read()["rules"] if r["id"] == rule_id), None)


def _norm_folder(v, label):
    try:
        return validate_folder_name(v)
    except MailError as exc:
        raise MailError(f"{label}: {exc.message}", 400, "invalid_rule")


def _validate_fields(data: dict, partial: bool) -> dict:
    out = {}
    if not partial or "name" in data:
        name = data.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise MailError("name は1〜100文字で指定してください", 400, "invalid_rule")
        out["name"] = name.strip()
    if "enabled" in data:
        if not isinstance(data["enabled"], bool):
            raise MailError("enabled は true/false で指定してください", 400, "invalid_rule")
        out["enabled"] = data["enabled"]
    if "priority" in data and data["priority"] is not None:
        p = data["priority"]
        if isinstance(p, bool) or not isinstance(p, int) or not (-100000 <= p <= 100000):
            raise MailError("priority は整数で指定してください（小さいほど優先）", 400, "invalid_rule")
        out["priority"] = p
    if "source_folder" in data and data["source_folder"] is not None or not partial:
        sf = data.get("source_folder") or "INBOX"
        out["source_folder"] = "INBOX" if is_inbox(sf) else _norm_folder(sf, "source_folder")
    if not partial or "target_folder" in data:
        tf = _norm_folder(data.get("target_folder"), "target_folder")
        if special_kind(tf):
            raise MailError("特殊フォルダ（送信済み・下書き・ゴミ箱・迷惑メール）は移動先にできません", 400, "invalid_rule")
        out["target_folder"] = tf
    if not partial or "condition" in data:
        try:
            out["condition"] = validate_condition(data.get("condition"))
        except ConditionError as exc:
            raise MailError(f"condition: {exc}", 400, "invalid_condition")
    return out


def create_rule(data: dict) -> dict:
    f = _validate_fields(data, partial=False)
    if f["target_folder"] == f["source_folder"]:
        raise MailError("移動元と移動先が同じです", 400, "invalid_rule")

    def fn(d):
        rules = d["rules"]
        prio = f.get("priority")
        if prio is None:
            prio = (max((r["priority"] for r in rules), default=0) // 10 + 1) * 10
        rule = {"id": "r_" + secrets.token_hex(4), "name": f["name"], "enabled": f.get("enabled", True),
                "priority": prio, "source_folder": f["source_folder"], "target_folder": f["target_folder"],
                "condition": f["condition"], "created_at": now(), "updated_at": now(), "warning": None}
        rules.append(rule)
        return rule

    rule = _rules.update(fn)
    _reset_state(rule["id"])
    return rule


def update_rule(rule_id: str, data: dict) -> tuple[dict, bool]:
    """戻り値: (更新後ルール, 全件再判定が必要か)"""
    f = _validate_fields(data, partial=True)
    holder = {}

    def fn(d):
        rule = next((r for r in d["rules"] if r["id"] == rule_id), None)
        if rule is None:
            raise MailError("ルールが見つかりません", 404, "rule_not_found")
        rescan = False
        for key in ("condition", "target_folder", "source_folder"):
            if key in f and f[key] != rule[key]:
                rescan = True
        if f.get("enabled") is True and not rule["enabled"]:
            rescan = True
        if "target_folder" in f or f.get("enabled") is True:
            rule["warning"] = None
        rule.update(f)
        if rule["target_folder"] == rule["source_folder"]:
            raise MailError("移動元と移動先が同じです", 400, "invalid_rule")
        rule["updated_at"] = now()
        holder["rule"] = dict(rule)
        return rescan

    rescan = _rules.update(fn)
    if rescan:
        _reset_state(rule_id)
    return holder["rule"], rescan


def delete_rule(rule_id: str) -> bool:
    def fn(d):
        n = len(d["rules"])
        d["rules"] = [r for r in d["rules"] if r["id"] != rule_id]
        return len(d["rules"]) != n

    ok = _rules.update(fn)
    if ok:
        _state.update(lambda s: s.pop(rule_id, None))
    return ok


def _reset_state(rule_id: str):
    _state.update(lambda s: s.__setitem__(rule_id, {"mode": "full"}))


# ------------------------------------------------------------ フォルダ変更への追従
def _repl(name: str, old: str, new: str):
    if name == old:
        return new
    if name.startswith(old + "/"):
        return new + name[len(old):]
    return name


def on_folder_renamed(old: str, new: str) -> int:
    changed = []

    def fn(d):
        for r in d["rules"]:
            s, t = _repl(r["source_folder"], old, new), _repl(r["target_folder"], old, new)
            if (s, t) != (r["source_folder"], r["target_folder"]):
                r["source_folder"], r["target_folder"] = s, t
                changed.append(r["id"])

    _rules.update(fn)

    def sfn(s):
        for st in s.values():
            wm = st.get("watermarks", {})
            for k in list(wm):
                nk = _repl(k, old, new)
                if nk != k:
                    wm[nk] = wm.pop(k)
            full = st.get("full")
            if full:
                full["done"] = [_repl(x, old, new) for x in full.get("done", [])]

    _state.update(sfn)
    return len(changed)


def on_folder_deleted(name: str) -> list[dict]:
    """削除フォルダに関係するルールを無効化して警告を付ける。影響したルールを返す。"""
    affected = []

    def fn(d):
        for r in d["rules"]:
            hit_t = r["target_folder"] == name or r["target_folder"].startswith(name + "/")
            hit_s = r["source_folder"] == name or r["source_folder"].startswith(name + "/")
            if not (hit_t or hit_s):
                continue
            kind = "移動先" if hit_t else "移動元"
            r["enabled"] = False
            r["warning"] = (f"{kind}フォルダ『{name}』が削除されたため、このルールは自動的に無効化されました。"
                            f"{kind}フォルダを変更してから有効化してください。")
            affected.append({"id": r["id"], "name": r["name"], "warning": r["warning"]})

    _rules.update(fn)
    return affected


# ------------------------------------------------------------ 実行
def _scan_scope(session, rule: dict) -> list[str]:
    """全件再判定の対象: INBOX + ラベルフォルダ（特殊フォルダ・自分の移動先を除く）"""
    names = ["INBOX"]
    for f in session.list_folders(counts=False):
        n = f["name"]
        if f["selectable"] and not is_inbox(n) and not f["special"]:
            names.append(n)
    if rule["source_folder"] not in names and not special_kind(rule["source_folder"]):
        names.append(rule["source_folder"])
    return [n for n in names if n != rule["target_folder"]]


def _samples(session, folder, uids, n=5):
    try:
        return [{"uid": h["uid"], "folder": folder, "subject": h["subject"], "from": h["from"]}
                for h in session.fetch_headers(folder, uids[:n])]
    except MailError:
        return []


def _move_batches(session, folder, uids, target, dry_run, deadline) -> tuple[int, bool]:
    """戻り値: (処理件数, 時間切れ)"""
    if dry_run:
        return len(uids), False
    done = 0
    for i in range(0, len(uids), BATCH):
        if i and time.monotonic() > deadline:
            return done, True
        chunk = uids[i:i + BATCH]
        session.move(folder, chunk, target)
        done += len(chunk)
    return done, False


def _run_one(session, rule, higher, state, dry_run, deadline) -> dict:
    res = {"rule_id": rule["id"], "name": rule["name"], "mode": state.get("mode", "full"),
           "moved": 0, "incomplete": False, "samples": [], "error": None}
    cond = rule["condition"]
    source = rule["source_folder"]
    try:
        info = session.folder_state(source)
    except MailError:
        res["error"] = f"移動元フォルダ『{source}』が見つかりません"
        return res

    if state.get("mode") == "diff":
        wm = state.get("watermarks", {}).get(source)
        if not wm or wm.get("uidvalidity") != info["uidvalidity"]:
            state = {"mode": "full"}  # UIDVALIDITY変更 → 全件再判定
            res["mode"] = "full"
        else:
            snapshot_last = info["uidnext"] - 1
            if snapshot_last > wm["last_uid"]:
                uids = session.search(source, cond, uid_from=wm["last_uid"] + 1)
                if uids:
                    res["samples"] = _samples(session, source, uids)
                    n, over = _move_batches(session, source, uids, rule["target_folder"], dry_run, deadline)
                    res["moved"] = n
                    if over:
                        res["incomplete"] = True
                        return res  # 位置は進めず次回再検索（移動済みは除外される）
                if not dry_run:
                    wm["last_uid"] = snapshot_last
            return _finish(res, state, dry_run)

    # ---- 全件再判定
    full = state.get("full") or {}
    if "snapshot" not in full:
        full = {"snapshot": {"uidvalidity": info["uidvalidity"], "uidnext": info["uidnext"]}, "done": []}
    scope = _scan_scope(session, rule)
    done = list(full.get("done", []))
    for folder in scope:
        if folder in done:
            continue
        if time.monotonic() > deadline:
            res["incomplete"] = True
            break
        try:
            uids = session.search(folder, cond, exclude=higher or None)
        except MailError:
            done.append(folder)
            continue
        if uids:
            if len(res["samples"]) < 5:
                res["samples"] += _samples(session, folder, uids, 5 - len(res["samples"]))
            n, over = _move_batches(session, folder, uids, rule["target_folder"], dry_run, deadline)
            res["moved"] += n
            if over:
                res["incomplete"] = True
                break
        done.append(folder)
    if res["incomplete"]:
        if not dry_run:
            state = {"mode": "full", "full": {"snapshot": full["snapshot"], "done": done}}
            _state.update(lambda s: s.__setitem__(rule["id"], state))
        return res
    if not dry_run:
        state = {"mode": "diff", "watermarks": {source: {
            "uidvalidity": full["snapshot"]["uidvalidity"], "last_uid": full["snapshot"]["uidnext"] - 1}}}
        _state.update(lambda s: s.__setitem__(rule["id"], state))
    return res


def _finish(res, state, dry_run):
    if not dry_run:
        _state.update(lambda s: s.__setitem__(res["rule_id"], state))
    return res


def run_rules(session, *, rule_id: str | None = None, dry_run: bool = False, budget: float | None = None) -> dict:
    from config import get_settings
    budget = get_settings().run_budget_seconds if budget is None else budget
    deadline = time.monotonic() + budget
    try:
        lock = file_lock("rules-run", blocking=False)
        lock.__enter__()
    except BlockingIOError:
        raise MailError("別の振り分け処理が実行中です。しばらくしてからやり直してください", 409, "busy")
    try:
        all_rules = list_rules()
        enabled = [r for r in all_rules if r["enabled"]]
        states = _state.read()
        results, incomplete = [], False
        for idx, rule in enumerate(enabled):
            if rule_id and rule["id"] != rule_id:
                continue
            higher = [r["condition"] for r in enabled[:idx]]
            r = _run_one(session, rule, higher, states.get(rule["id"], {"mode": "full"}), dry_run, deadline)
            results.append(r)
            if r["incomplete"]:
                incomplete = True
                break  # 優先度の低いルールは、高いルールの再判定が終わるまで待つ
        skipped = [{"id": r["id"], "name": r["name"], "reason": r["warning"] or "無効化されています"}
                   for r in all_rules if not r["enabled"] and (not rule_id or r["id"] == rule_id)]
        return {"dry_run": dry_run, "results": results, "incomplete": incomplete,
                "total_moved": sum(r["moved"] for r in results),
                "disabled_rules": skipped,
                "note": ("時間制限のため途中で終了しました。もう一度実行すると続きから再開します。" if incomplete else None)}
    finally:
        lock.__exit__(None, None, None)


def preview(session, condition: dict, source_folder: str = "INBOX", limit: int = 20) -> dict:
    try:
        cond = validate_condition(condition)
    except ConditionError as exc:
        raise MailError(f"condition: {exc}", 400, "invalid_condition")
    uids = session.search(source_folder, cond)
    top = uids[-limit:][::-1]
    return {"total": len(uids), "folder": source_folder, "samples": session.fetch_headers(source_folder, top)}
