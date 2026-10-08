"""IMAPなしで動作確認するためのモックセッション（ローカル開発・テスト専用）。imap_client.RealSession と同じインターフェース。"""
import copy
import datetime as dt
import threading

from html_text import html_to_text
from imap_client import MailError, is_inbox, special_kind, validate_folder_name
from search_builder import matches

_LOCK = threading.RLock()
_STORE: dict | None = None
DELIM = "/"


def _msg(subject, frm, name="", to="me@example.com", body="", html=None, hours_ago=1, seen=False,
         headers=None, size=None, attachments=None, flags=None):
    h = {k.lower(): [v] for k, v in (headers or {}).items()}
    fl = set(flags or [])
    if seen:
        fl.add("\\Seen")
    return {
        "subject": subject, "from_addr": frm, "from_name": name, "to": [to], "cc": [], "bcc": [],
        "body": body, "html": html, "headers": h,
        "date": dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_ago),
        "size": size if size is not None else 2048 + len(body) + len(html or ""),
        "flags": fl, "attachments": attachments or [],
    }


def _seed() -> dict:
    inbox = [
        _msg("【リクナビ】エントリー受付完了のお知らせ", "info@rikunabi.com", "リクナビ", body="株式会社サンプルへのエントリーを受け付けました。", hours_ago=2),
        _msg("【マイナビ】今週の新着求人メルマガ", "news@mynavi.jp", "マイナビ", body="新着求人をお届けします。", hours_ago=5, headers={"List-Id": "<news.mynavi.jp>"}),
        _msg("一次面接日程のご案内", "recruit@company-a.co.jp", "A社 採用担当", body="面接日程の候補は以下です。10/20 10:00 / 10/21 14:00", hours_ago=7, seen=True),
        _msg("選考結果のお知らせ", "hr@company-b.example", "B社人事部", body="慎重に選考を重ねた結果、今回は見送りとなりました。", hours_ago=26),
        _msg("ご注文の確認", "order-update@amazon.co.jp", "Amazon.co.jp", body="ご注文ありがとうございます。", hours_ago=30, seen=True),
        _msg("[job-hunt] Pull request #12 merged", "notifications@github.com", "GitHub", body="Merged #12.", hours_ago=40, headers={"List-Id": "<job-hunt.github.com>"}),
        _msg("週末の予定", "friend@example.org", "田中", body="今週末どうする？", hours_ago=48, seen=True),
        _msg("【キャリタス】会社説明会のご案内", "info@career-tasu.example", "キャリタス", html="<html><head><style>p{color:red}</style></head><body><p>会社説明会を開催します。</p><p>日時：<b>11/5</b></p><script>alert(1)</script></body></html>", hours_ago=60),
        _msg("【重要】適性検査の受検のお願い", "recruit@company-c.example", "C社", body="Webテストを受検してください。", hours_ago=70, attachments=[{"filename": "guide.pdf", "size": 120000, "content_type": "application/pdf"}], size=130000),
        _msg("請求書送付のお知らせ", "billing@service.example", "サービス事務局", body="今月分の請求書です。", hours_ago=90),
    ]
    for i in range(1, 11):
        inbox.append(_msg(f"お知らせ #{i}", "noreply@service.example", "サービス", body=f"定期のお知らせ {i}", hours_ago=100 + i * 5, seen=(i % 2 == 0)))
    folders = {"INBOX": inbox,
               "Sent": [_msg("Re: 面接日程", "me@example.com", "自分", to="recruit@company-a.co.jp", body="よろしくお願いします。", hours_ago=6, seen=True)],
               "Drafts": [], "Trash": [_msg("削除済みメール", "x@example.com", "X", body="...", hours_ago=200, seen=True)], "Junk": [_msg("当選のお知らせ", "spam@spam.example", "spam", body="おめでとう", hours_ago=300)],
               "就活": [], "就活/選考中": []}
    store = {}
    for name, msgs in folders.items():
        d = {"uidvalidity": 1, "uidnext": 1, "messages": {}}
        for m in msgs:
            d["messages"][d["uidnext"]] = m
            d["uidnext"] += 1
        store[name] = d
    return store


def reset_mock():
    global _STORE
    with _LOCK:
        _STORE = _seed()


def _store() -> dict:
    global _STORE
    if _STORE is None:
        reset_mock()
    return _STORE


def _view(m: dict) -> dict:
    body = m["body"] if m["body"] else html_to_text(m["html"] or "")
    frm = f'{m["from_name"]} <{m["from_addr"]}>' if m["from_name"] else m["from_addr"]
    return {"from": frm, "to": " ".join(m["to"]), "cc": " ".join(m["cc"]), "bcc": " ".join(m["bcc"]),
            "subject": m["subject"], "body": body, "headers": m["headers"], "date": m["date"],
            "size": m["size"], "flags": m["flags"]}


class MockSession:
    delim = DELIM

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def close(self):
        pass

    def _folder(self, name: str) -> dict:
        st = _store()
        if name not in st:
            raise MailError(f"フォルダ '{name}' が見つかりません", 404, "folder_not_found")
        return st[name]

    # -- フォルダ
    def list_folders(self, counts: bool = True) -> list[dict]:
        out = []
        for name, f in _store().items():
            out.append({"name": name, "special": special_kind(name), "selectable": True,
                        "total": len(f["messages"]) if counts else None,
                        "unread": sum(1 for m in f["messages"].values() if "\\Seen" not in m["flags"]) if counts else None})
        out.sort(key=lambda x: (not is_inbox(x["name"]), x["name"]))
        return out

    def folder_exists(self, name: str) -> bool:
        return name in _store()

    def create_folder(self, name: str):
        name = validate_folder_name(name, DELIM)
        with _LOCK:
            segs = name.split("/")
            for i in range(1, len(segs) + 1):
                part = "/".join(segs[:i])
                if part not in _store():
                    _store()[part] = {"uidvalidity": 1, "uidnext": 1, "messages": {}}

    def rename_folder(self, old: str, new: str):
        with _LOCK:
            st = _store()
            if old not in st:
                raise MailError(f"フォルダ '{old}' が見つかりません", 404, "folder_not_found")
            if new in st:
                raise MailError(f"フォルダ '{new}' は既に存在します", 409, "folder_exists")
            for name in sorted([n for n in st if n == old or n.startswith(old + "/")]):
                st[new + name[len(old):]] = st.pop(name)

    def delete_folder_raw(self, name: str):
        with _LOCK:
            self._folder(name)
            del _store()[name]

    def folder_state(self, name: str) -> dict:
        f = self._folder(name)
        return {"uidvalidity": f["uidvalidity"], "uidnext": f["uidnext"], "total": len(f["messages"]),
                "unread": sum(1 for m in f["messages"].values() if "\\Seen" not in m["flags"])}

    # -- メール
    def search(self, folder, cond=None, *, unread=False, exclude=None, uid_from=None) -> list[int]:
        f = self._folder(folder)
        out = []
        for uid, m in f["messages"].items():
            if uid_from is not None and uid < uid_from:
                continue
            v = _view(m)
            if cond and not matches(cond, v):
                continue
            if unread and "\\Seen" in m["flags"]:
                continue
            if any(matches(e, v) for e in (exclude or [])):
                continue
            out.append(uid)
        return sorted(out)

    def _header(self, folder, uid, m) -> dict:
        return {"uid": uid, "folder": folder, "subject": m["subject"], "from": m["from_addr"],
                "from_name": m["from_name"], "to": list(m["to"]), "date": m["date"].isoformat(),
                "seen": "\\Seen" in m["flags"], "flags": sorted(m["flags"]),
                "has_attachments": bool(m["attachments"]), "size": m["size"]}

    def fetch_headers(self, folder, uids) -> list[dict]:
        f = self._folder(folder)
        return [self._header(folder, u, f["messages"][u]) for u in uids if u in f["messages"]]

    def fetch_message(self, folder, uid, max_chars=None):
        f = self._folder(folder)
        m = f["messages"].get(uid)
        if not m:
            return None
        text, source = m["body"] or "", "text"
        if not text.strip() and m["html"]:
            text, source = html_to_text(m["html"]), "html"
        full, truncated = len(text), False
        if max_chars is not None and full > max_chars:
            text, truncated = text[:max_chars], True
        out = self._header(folder, uid, m)
        out.update({"cc": list(m["cc"]), "text": text, "text_source": source, "text_length": full,
                    "truncated": truncated, "headers": {k: v[0] for k, v in m["headers"].items()},
                    "attachments": copy.deepcopy(m["attachments"])})
        return out

    def move(self, folder, uids, target):
        with _LOCK:
            src = self._folder(folder)
            if target not in _store():
                self.create_folder(target)
            dst = self._folder(target)
            for u in uids:
                m = src["messages"].pop(u, None)
                if m is not None:
                    dst["messages"][dst["uidnext"]] = m
                    dst["uidnext"] += 1

