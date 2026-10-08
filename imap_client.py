"""IMAP処理（imap_tools）。

方針:
- メールは絶対に既読にしない（取得は常に BODY.PEEK / EXAMINE（読み取り専用）、\\Seen を変更するコードを持たない）。
- フォルダ名は API 上 `/` 区切りの日本語名。サーバーの区切り文字・名前空間接頭辞へは自動変換する。
"""
import re
import sys
import traceback
from datetime import datetime, timezone

from config import Settings, get_settings
from html_text import html_to_text
from search_builder import build_query

SPECIAL_FLAGS = {"\\sent": "sent", "\\drafts": "drafts", "\\trash": "trash", "\\junk": "junk"}
SPECIAL_NAMES = {
    "sent": "sent", "sent items": "sent", "sent messages": "sent", "sent mail": "sent",
    "送信済み": "sent", "送信済みアイテム": "sent", "送信済みメール": "sent",
    "drafts": "drafts", "draft": "drafts", "下書き": "drafts",
    "trash": "trash", "deleted items": "trash", "deleted messages": "trash", "bin": "trash",
    "ごみ箱": "trash", "削除済み": "trash", "削除済みアイテム": "trash", "ゴミ箱": "trash",
    "junk": "junk", "spam": "junk", "junk e-mail": "junk", "junk email": "junk", "bulk mail": "junk",
    "迷惑メール": "junk", "スパム": "junk",
}
MAX_FOLDER_NAME = 120


class MailError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "bad_request", extra: dict | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.extra = extra or {}


# ------------------------------------------------------------ フォルダ名ユーティリティ
def is_inbox(name: str) -> bool:
    return name.upper() == "INBOX"


def special_kind(api_name: str, flags=()) -> str | None:
    for f in flags:
        k = SPECIAL_FLAGS.get(f.lower())
        if k:
            return k
    return SPECIAL_NAMES.get(api_name.strip().casefold())


def validate_folder_name(name, delim: str = "/") -> str:
    if not isinstance(name, str) or not name.strip():
        raise MailError("フォルダ名を指定してください", 400, "invalid_folder")
    name = name.strip()
    if len(name) > MAX_FOLDER_NAME:
        raise MailError(f"フォルダ名は{MAX_FOLDER_NAME}文字以内にしてください", 400, "invalid_folder")
    if any(ord(c) < 32 or c in '%*\\"' for c in name):
        raise MailError('フォルダ名に使えない文字（制御文字 % * \\ "）が含まれています', 400, "invalid_folder")
    segs = name.split("/")
    if any(not s.strip() or s != s.strip() for s in segs) or name.startswith("/"):
        raise MailError("フォルダ名の区切り（/）の前後に空の名前は使えません", 400, "invalid_folder")
    if delim != "/" and delim in name:
        raise MailError(f"フォルダ名に '{delim}' は使えません（このサーバーのフォルダ区切り文字です）", 400, "invalid_folder")
    if is_inbox(segs[0]) and len(segs) == 1:
        raise MailError("INBOX は予約名です", 400, "invalid_folder")
    return name


def _ts(iso_or_dt) -> float:
    d = iso_or_dt
    if isinstance(d, str):
        try:
            d = datetime.fromisoformat(d)
        except ValueError:
            return 0.0
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


# ------------------------------------------------------------ 実IMAPセッション
class RealSession:
    def __init__(self, settings: Settings):
        import ssl
        from imap_tools import MailBoxStartTls
        self.delim = "/"
        self.prefix = ""
        self._current: tuple[str, bool] | None = None
        try:
            mb = MailBoxStartTls(settings.imap_host, settings.imap_port, timeout=40,
                                 ssl_context=ssl.create_default_context())
            mb.login(settings.imap_user, settings.imap_password, initial_folder=None)
        except Exception:
            traceback.print_exc(file=sys.stderr)
            raise MailError("IMAPサーバーに接続またはログインできませんでした", 502, "imap_connect")
        self.mb = mb
        self._detect_namespace()

    # -- 内部
    def _detect_namespace(self):
        try:
            _, data = self.mb.client.namespace()
            text = b" ".join(d for d in data if isinstance(d, bytes)).decode("utf-8", "replace")
            m = re.search(r'\(\("([^"]*)" (?:"(.)"|NIL)', text)
            if m:
                self.prefix = m.group(1)
                if m.group(2):
                    self.delim = m.group(2)
                    return
        except Exception:
            pass
        try:
            for fi in self.mb.folder.list(search_args="INBOX"):
                if fi.delim and fi.delim != "NIL":
                    self.delim = fi.delim
                    break
        except Exception:
            pass

    def _srv(self, api_name: str) -> str:
        if is_inbox(api_name):
            return "INBOX"
        return self.prefix + api_name.replace("/", self.delim)

    def _api(self, server_name: str) -> str:
        n = server_name
        if is_inbox(n):
            return "INBOX"
        if self.prefix and n.startswith(self.prefix):
            n = n[len(self.prefix):]
        return n.replace(self.delim, "/") if self.delim != "/" else n

    def _select(self, folder: str, readonly: bool):
        key = (folder, readonly)
        if self._current == key:
            return
        try:
            self.mb.folder.set(self._srv(folder), readonly=readonly)
        except Exception:
            self._current = None
            raise MailError(f"フォルダ '{folder}' を開けませんでした", 404, "folder_not_found")
        self._current = key

    def close(self):
        try:
            self.mb.logout()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- フォルダ
    def list_folders(self, counts: bool = True) -> list[dict]:
        out, seen = [], set()
        for fi in self.mb.folder.list():
            name = self._api(fi.name)
            if not name or name in seen:
                continue
            seen.add(name)
            flags = {f.lower() for f in fi.flags}
            selectable = "\\noselect" not in flags and "\\nonexistent" not in flags
            item = {"name": name, "special": special_kind(name, flags), "selectable": selectable,
                    "total": None, "unread": None}
            if counts and selectable:
                try:
                    st = self.mb.folder.status(fi.name)
                    item["total"], item["unread"] = st.get("MESSAGES"), st.get("UNSEEN")
                except Exception:
                    pass
            out.append(item)
        if "INBOX" not in seen:
            out.append({"name": "INBOX", "special": None, "selectable": True, "total": None, "unread": None})
        out.sort(key=lambda f: (not is_inbox(f["name"]), f["name"]))
        return out

    def folder_exists(self, name: str) -> bool:
        return is_inbox(name) or self.mb.folder.exists(self._srv(name))

    def create_folder(self, name: str):
        name = validate_folder_name(name, self.delim)
        segs = name.split("/")
        for i in range(1, len(segs) + 1):
            part = "/".join(segs[:i])
            if not self.folder_exists(part):
                try:
                    self.mb.folder.create(self._srv(part))
                    self.mb.folder.subscribe(self._srv(part), True)
                except Exception:
                    traceback.print_exc(file=sys.stderr)
                    raise MailError(f"フォルダ '{part}' を作成できませんでした", 502, "folder_create_failed")

    def rename_folder(self, old: str, new: str):
        try:
            self.mb.folder.rename(self._srv(old), self._srv(new))
            try:
                self.mb.folder.subscribe(self._srv(new), True)
            except Exception:
                pass
        except Exception:
            traceback.print_exc(file=sys.stderr)
            raise MailError("フォルダ名を変更できませんでした", 502, "folder_rename_failed")
        self._current = None

    def delete_folder_raw(self, name: str):
        try:
            try:
                self.mb.folder.subscribe(self._srv(name), False)
            except Exception:
                pass
            self.mb.folder.delete(self._srv(name))
        except Exception:
            traceback.print_exc(file=sys.stderr)
            raise MailError("フォルダを削除できませんでした", 502, "folder_delete_failed")
        self._current = None

    def folder_state(self, name: str) -> dict:
        try:
            st = self.mb.folder.status(self._srv(name))
        except Exception:
            raise MailError(f"フォルダ '{name}' が見つかりません", 404, "folder_not_found")
        return {"uidvalidity": st.get("UIDVALIDITY", 0), "uidnext": st.get("UIDNEXT", 1),
                "total": st.get("MESSAGES", 0), "unread": st.get("UNSEEN", 0)}

    # -- メール
    def search(self, folder: str, cond: dict | None = None, *, unread: bool = False,
               exclude: list[dict] | None = None, uid_from: int | None = None) -> list[int]:
        self._select(folder, True)
        q = build_query(cond, unread=unread, exclude=exclude, uid_from=uid_from)
        charset = None if q.isascii() else "UTF-8"
        try:
            raw = self.mb.uids(q, charset=charset)
        except Exception:
            traceback.print_exc(file=sys.stderr)
            raise MailError("メールの検索に失敗しました（この条件はIMAPサーバーが対応していない可能性があります）", 502, "imap_search")
        uids = sorted(int(u) for u in raw)
        if uid_from is not None:
            uids = [u for u in uids if u >= uid_from]  # `n:*` は n が最大UIDを超えると最後のメールを返すため
        return uids

    def fetch_headers(self, folder: str, uids: list[int]) -> list[dict]:
        if not uids:
            return []
        self._select(folder, True)
        out = []
        for m in self.mb.fetch(uid_list=[str(u) for u in uids], headers_only=True, mark_seen=False,
                               bulk=50, charset=None):
            ctype = " ".join(m.headers.get("content-type", ()) or ()).lower()
            frm = m.from_values
            out.append({
                "uid": int(m.uid), "folder": folder, "subject": m.subject or "",
                "from": m.from_ or "", "from_name": (frm.name if frm else "") or "",
                "to": list(m.to or ()), "date": m.date.isoformat() if m.date else "",
                "seen": "\\Seen" in m.flags, "flags": list(m.flags),
                "has_attachments": "multipart/mixed" in ctype or "multipart/signed" in ctype,
                "size": m.size_rfc822 if hasattr(m, "size_rfc822") else m.size,
            })
        return out

    def fetch_message(self, folder: str, uid: int, max_chars: int | None = None) -> dict | None:
        self._select(folder, True)
        for m in self.mb.fetch(uid_list=[str(uid)], headers_only=False, mark_seen=False, charset=None):
            text = m.text or ""
            source = "text"
            if not text.strip() and m.html:
                text, source = html_to_text(m.html), "html"
            full_len = len(text)
            truncated = False
            if max_chars is not None and full_len > max_chars:
                text, truncated = text[:max_chars], True
            hdrs = {}
            for key in ("message-id", "reply-to", "list-id", "cc", "in-reply-to"):
                v = m.headers.get(key)
                if v:
                    hdrs[key] = " ".join(v)
            frm = m.from_values
            return {
                "uid": int(m.uid), "folder": folder, "subject": m.subject or "",
                "from": m.from_ or "", "from_name": (frm.name if frm else "") or "",
                "to": list(m.to or ()), "cc": list(m.cc or ()), "date": m.date.isoformat() if m.date else "",
                "seen": "\\Seen" in m.flags, "flags": list(m.flags), "size": getattr(m, "size_rfc822", m.size),
                "text": text, "text_source": source, "text_length": full_len, "truncated": truncated,
                "headers": hdrs,
                "attachments": [{"filename": a.filename or "", "size": a.size, "content_type": a.content_type}
                                for a in m.attachments],
                "has_attachments": bool(m.attachments),
            }
        return None

    def move(self, folder: str, uids: list[int], target: str):
        if not uids:
            return
        self.create_folder(target) if not self.folder_exists(target) else None
        self._select(folder, False)
        try:
            self.mb.move([str(u) for u in uids], self._srv(target), chunks=300)
        except Exception:
            traceback.print_exc(file=sys.stderr)
            raise MailError("メールの移動に失敗しました", 502, "imap_move")
        self._current = None


def open_session(settings: Settings | None = None):
    """IMAPセッションを返す（context manager対応）。IMAP_MOCK=1 ならモック。"""
    s = settings or get_settings()
    if s.imap_mock:
        from mock_imap_client import MockSession
        return MockSession()
    return RealSession(s)


class IMAPManager:
    def get_folders(self) -> dict:
        with open_session() as s:
            return {"folders": s.list_folders()}

    def create_folder(self, name: str):
        with open_session() as s:
            s.create_folder(name)

    def rename_folder(self, old: str, new: str):
        with open_session() as s:
            s.rename_folder(old, new)

    def delete_folder(self, name: str):
        with open_session() as s:
            s.delete_folder_raw(name)

    def get_recent_emails(self, folder="INBOX", limit=10, offset=0, unread_only=False,
                          subject=None, from_address=None, to_address=None, condition_tree=None) -> list[dict]:
        with open_session() as s:
            conds = []
            if subject:
                conds.append({"field": "subject", "op": "contains", "value": subject})
            if from_address:
                conds.append({"field": "from", "op": "contains", "value": from_address})
            if to_address:
                conds.append({"field": "to", "op": "contains", "value": to_address})
            if condition_tree:
                conds.append(condition_tree)

            combined_cond = None
            if len(conds) == 1:
                combined_cond = conds[0]
            elif len(conds) > 1:
                combined_cond = {"type": "AND", "conditions": conds}

            uids = s.search(folder, cond=combined_cond, unread=unread_only)
            # 新しい順 (UID降順)
            uids.reverse()
            sliced = uids[offset:offset + limit]
            return s.fetch_headers(folder, sliced)

    def get_email(self, uid, folder="INBOX", max_chars=20000) -> dict | None:
        with open_session() as s:
            return s.fetch_message(folder, int(uid), max_chars=max_chars)

    def move_email(self, uid, target_folder, source_folder="INBOX"):
        with open_session() as s:
            s.move(source_folder, [int(uid)], target_folder)


def get_imap_client() -> IMAPManager:
    return IMAPManager()

