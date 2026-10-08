"""条件ツリー → IMAP SEARCH 文字列への変換と、同じ条件を評価するPython実装（モック/テスト用）。

条件ツリー:
  {"all": [node, ...]} / {"any": [node, ...]} / {"not": node}
  {"field": "from|to|cc|bcc|subject|body|text", "op": "contains|not_contains|contains_any|contains_all|not_contains_any", "value": str|[str]}
  {"field": "header", "name": "List-Id", "op": "contains|not_contains|exists|not_exists", "value": str}
  {"field": "date", "op": "since|before|within_days|older_than_days", "value": "YYYY-MM-DD" | int}
  {"field": "size", "op": "larger_than|smaller_than", "value": KB}
  {"field": "state", "op": "is", "value": "unread|read|flagged|unflagged|answered|unanswered"}
正規表現・完全一致・前方/後方一致はIMAP SEARCHの仕様上できない。
"""
import datetime as dt
import re

TEXT_FIELDS = {"from": "FROM", "to": "TO", "cc": "CC", "bcc": "BCC",
               "subject": "SUBJECT", "body": "BODY", "text": "TEXT"}
TEXT_OPS = {"contains", "not_contains", "contains_any", "contains_all", "not_contains_any"}
HEADER_OPS = {"contains", "not_contains", "exists", "not_exists"}
DATE_OPS = {"since", "before", "within_days", "older_than_days"}
SIZE_OPS = {"larger_than", "smaller_than"}
STATES = {"unread": "UNSEEN", "read": "SEEN", "flagged": "FLAGGED",
          "unflagged": "UNFLAGGED", "answered": "ANSWERED", "unanswered": "UNANSWERED"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

MAX_DEPTH = 6
MAX_NODES = 60
MAX_STR = 200
HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9-]{1,60}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ConditionError(ValueError):
    pass


# ---------------------------------------------------------------- 検証
def _check_str(v, label="値"):
    if not isinstance(v, str) or not v.strip():
        raise ConditionError(f"{label}は空でない文字列にしてください")
    if len(v) > MAX_STR:
        raise ConditionError(f"{label}は{MAX_STR}文字以内にしてください")
    if any(c in v for c in "\r\n\x00"):
        raise ConditionError(f"{label}に改行・制御文字は使えません")
    return v


def validate_condition(node, _depth=0, _count=None):
    """検証して正規化したツリーを返す。不正なら ConditionError。"""
    if _count is None:
        _count = [0]
    _count[0] += 1
    if _count[0] > MAX_NODES:
        raise ConditionError(f"条件が多すぎます（最大{MAX_NODES}個）")
    if _depth > MAX_DEPTH:
        raise ConditionError(f"条件の入れ子が深すぎます（最大{MAX_DEPTH}段）")
    if not isinstance(node, dict):
        raise ConditionError("条件はオブジェクトで指定してください")
    keys = set(node)
    if keys == {"all"} or keys == {"any"}:
        kind = next(iter(keys))
        items = node[kind]
        if not isinstance(items, list) or not items:
            raise ConditionError(f"'{kind}' には1つ以上の条件が必要です")
        return {kind: [validate_condition(c, _depth + 1, _count) for c in items]}
    if keys == {"not"}:
        return {"not": validate_condition(node["not"], _depth + 1, _count)}

    field = node.get("field")
    op = node.get("op")
    if field in TEXT_FIELDS:
        if op not in TEXT_OPS:
            raise ConditionError(f"{field} の演算 '{op}' は使えません（{sorted(TEXT_OPS)}）")
        val = node.get("value")
        if op in ("contains", "not_contains"):
            return {"field": field, "op": op, "value": _check_str(val)}
        if not isinstance(val, list) or not val or len(val) > 30:
            raise ConditionError("複数値の条件は1〜30個の文字列リストで指定してください")
        return {"field": field, "op": op, "value": [_check_str(v) for v in val]}
    if field == "header":
        name = node.get("name")
        if not isinstance(name, str) or not HEADER_NAME_RE.match(name):
            raise ConditionError("ヘッダー名は英数字とハイフンのみ（60文字以内）で指定してください")
        if op not in HEADER_OPS:
            raise ConditionError(f"header の演算 '{op}' は使えません（{sorted(HEADER_OPS)}）")
        out = {"field": "header", "name": name, "op": op}
        if op in ("contains", "not_contains"):
            out["value"] = _check_str(node.get("value"))
        return out
    if field == "date":
        if op not in DATE_OPS:
            raise ConditionError(f"date の演算 '{op}' は使えません（{sorted(DATE_OPS)}）")
        val = node.get("value")
        if op in ("since", "before"):
            if not isinstance(val, str) or not DATE_RE.match(val):
                raise ConditionError("日付は YYYY-MM-DD 形式で指定してください")
            try:
                dt.date.fromisoformat(val)
            except ValueError as exc:
                raise ConditionError("存在しない日付です") from exc
        else:
            if isinstance(val, bool) or not isinstance(val, int) or not (0 <= val <= 36500):
                raise ConditionError("日数は0以上の整数で指定してください")
        return {"field": "date", "op": op, "value": val}
    if field == "size":
        if op not in SIZE_OPS:
            raise ConditionError(f"size の演算 '{op}' は使えません（{sorted(SIZE_OPS)}）")
        val = node.get("value")
        if isinstance(val, bool) or not isinstance(val, (int, float)) or val < 0 or val > 10_000_000:
            raise ConditionError("サイズはKB単位の0以上の数値で指定してください")
        return {"field": "size", "op": op, "value": val}
    if field == "state":
        if op != "is" or node.get("value") not in STATES:
            raise ConditionError(f"state は op='is' と value={sorted(STATES)} のいずれかで指定してください")
        return {"field": "state", "op": "is", "value": node["value"]}
    raise ConditionError(f"不明な条件です: {node!r}"[:200])


# ---------------------------------------------------------------- IMAP SEARCH 変換
def quote(s: str) -> str:
    if any(c in s for c in "\r\n\x00"):
        raise ConditionError("制御文字は使えません")
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def imap_date(d: dt.date) -> str:
    return f"{d.day:02d}-{MONTHS[d.month - 1]}-{d.year}"


def _wrap(s: str) -> str:
    return f"({s})"


def _or_chain(parts: list[str]) -> str:
    if len(parts) == 1:
        return parts[0]
    return f"OR {_wrap(parts[0])} {_wrap(_or_chain(parts[1:]))}"


def to_imap(node: dict, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    if "all" in node:
        return " ".join(_wrap(to_imap(c, today)) for c in node["all"])
    if "any" in node:
        return _or_chain([to_imap(c, today) for c in node["any"]])
    if "not" in node:
        return f"NOT {_wrap(to_imap(node['not'], today))}"
    field, op = node["field"], node["op"]
    if field in TEXT_FIELDS:
        key = TEXT_FIELDS[field]
        val = node["value"]
        if op == "contains":
            return f"{key} {quote(val)}"
        if op == "not_contains":
            return f"NOT ({key} {quote(val)})"
        keys = [f"{key} {quote(v)}" for v in val]
        if op == "contains_any":
            return _or_chain(keys)
        if op == "not_contains_any":
            return f"NOT ({_or_chain(keys)})"
        return " ".join(_wrap(k) for k in keys)  # contains_all
    if field == "header":
        name = quote(node["name"])
        if op == "exists":
            return f'HEADER {name} ""'
        if op == "not_exists":
            return f'NOT (HEADER {name} "")'
        base = f"HEADER {name} {quote(node['value'])}"
        return base if op == "contains" else f"NOT ({base})"
    if field == "date":
        v = node["value"]
        if op == "since":
            return f"SINCE {imap_date(dt.date.fromisoformat(v))}"
        if op == "before":
            return f"BEFORE {imap_date(dt.date.fromisoformat(v))}"
        cutoff = today - dt.timedelta(days=v)
        return f"SINCE {imap_date(cutoff)}" if op == "within_days" else f"BEFORE {imap_date(cutoff)}"
    if field == "size":
        n = int(round(node["value"] * 1024))
        return f"{'LARGER' if op == 'larger_than' else 'SMALLER'} {n}"
    if field == "state":
        return STATES[node["value"]]
    raise ConditionError("unreachable")


def build_query(cond: dict | None, *, unread: bool = False, exclude: list[dict] | None = None,
                uid_from: int | None = None, today: dt.date | None = None) -> str:
    """検索文字列を作る。uid_from を指定すると `UID n:*`（※結果は呼び出し側で uid>=n に絞ること）。"""
    parts = []
    if cond:
        parts.append(_wrap(to_imap(cond, today)))
    if unread:
        parts.append("UNSEEN")
    for ex in exclude or []:
        parts.append(f"NOT {_wrap(to_imap(ex, today))}")
    if uid_from is not None:
        parts.append(f"UID {int(uid_from)}:*")
    return " ".join(parts) if parts else "ALL"


# ---------------------------------------------------------------- Python評価（モック用）
def _contains(hay: str, needle: str) -> bool:
    return needle.casefold() in (hay or "").casefold()


def matches(node: dict, msg: dict, today: dt.date | None = None) -> bool:
    """msg: {from,to,cc,bcc,subject,body (str), headers {lower-name: [str]}, date (datetime), size, flags(set)}"""
    today = today or dt.date.today()
    if "all" in node:
        return all(matches(c, msg, today) for c in node["all"])
    if "any" in node:
        return any(matches(c, msg, today) for c in node["any"])
    if "not" in node:
        return not matches(node["not"], msg, today)
    field, op = node["field"], node["op"]
    if field in TEXT_FIELDS:
        if field == "text":
            hay = " ".join(str(msg.get(k, "")) for k in ("from", "to", "cc", "bcc", "subject")) + " " + str(msg.get("body", ""))
        else:
            hay = str(msg.get(field, ""))
        val = node["value"]
        if op == "contains":
            return _contains(hay, val)
        if op == "not_contains":
            return not _contains(hay, val)
        if op == "contains_any":
            return any(_contains(hay, v) for v in val)
        if op == "not_contains_any":
            return not any(_contains(hay, v) for v in val)
        return all(_contains(hay, v) for v in val)
    if field == "header":
        vals = msg.get("headers", {}).get(node["name"].lower(), [])
        if op == "exists":
            return bool(vals)
        if op == "not_exists":
            return not vals
        hit = any(_contains(v, node["value"]) for v in vals)
        return hit if op == "contains" else not hit
    if field == "date":
        d = msg["date"].date() if hasattr(msg["date"], "date") else msg["date"]
        v = node["value"]
        if op == "since":
            return d >= dt.date.fromisoformat(v)
        if op == "before":
            return d < dt.date.fromisoformat(v)
        cutoff = today - dt.timedelta(days=v)
        return d >= cutoff if op == "within_days" else d < cutoff
    if field == "size":
        n = node["value"] * 1024
        return msg["size"] > n if op == "larger_than" else msg["size"] < n
    if field == "state":
        flags = msg.get("flags", set())
        return {
            "unread": "\\Seen" not in flags, "read": "\\Seen" in flags,
            "flagged": "\\Flagged" in flags, "unflagged": "\\Flagged" not in flags,
            "answered": "\\Answered" in flags, "unanswered": "\\Answered" not in flags,
        }[node["value"]]
    raise ConditionError("unreachable")
