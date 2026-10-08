"""排他ロック付きJSONファイル保存。CGIの同時実行（複数プロセス）に対応する。"""
import json
import os
import tempfile
import time
from contextlib import contextmanager

from config import get_settings

try:
    import fcntl  # POSIX

    def _lock(fh, blocking=True):
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        fcntl.flock(fh, flags)

    def _unlock(fh):
        fcntl.flock(fh, fcntl.LOCK_UN)
except ImportError:  # Windows（ローカル開発・テスト用）
    import msvcrt

    def _lock(fh, blocking=True):
        fh.seek(0)
        mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
        msvcrt.locking(fh.fileno(), mode, 1)

    def _unlock(fh):
        fh.seek(0)
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass


def data_path(name: str) -> str:
    d = get_settings().data_dir
    os.makedirs(d, mode=0o700, exist_ok=True)
    return os.path.join(d, name)


@contextmanager
def file_lock(name: str, blocking: bool = True):
    """名前付きロック。blocking=False でロック済みなら BlockingIOError。"""
    path = data_path(name + ".lock")
    fh = open(path, "a+")
    try:
        try:
            _lock(fh, blocking)
        except OSError as exc:
            raise BlockingIOError("locked") from exc
        try:
            yield
        finally:
            _unlock(fh)
    finally:
        fh.close()


class JsonStore:
    def __init__(self, filename: str, default):
        self.filename = filename
        self.default = default

    def _read_unlocked(self):
        path = data_path(self.filename)
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            return json.loads(json.dumps(self.default))
        except json.JSONDecodeError:
            return json.loads(json.dumps(self.default))

    def read(self):
        with file_lock(self.filename):
            return self._read_unlocked()

    def update(self, fn):
        """fn(data) -> result。dataはfn内で変更してよい。結果を返す。"""
        with file_lock(self.filename):
            data = self._read_unlocked()
            result = fn(data)
            path = data_path(self.filename)
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, ensure_ascii=False, indent=1)
                try:
                    os.chmod(tmp, 0o600)
                except OSError:
                    pass
                os.replace(tmp, path)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            return result


def now() -> float:
    return time.time()

