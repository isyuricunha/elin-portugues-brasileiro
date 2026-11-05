"""Bounded copy-on-write transactions and conservative rollback/recovery."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import stat
import time
import uuid

from native import Invalid


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(data):
    return data.replace(b"\r\n", b"\n")


def json_bytes(obj):
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2)+"\n").encode("utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def safe(root, rel):
    p = PurePosixPath(rel)
    if (not isinstance(rel, str) or not rel or "\\" in rel or ":" in rel
            or p.is_absolute() or any(x in {".", "..", ""} for x in rel.split("/"))):
        raise Invalid(f"UNSAFE_PATH: {rel}")
    root = Path(root).resolve()
    path = root
    for part in p.parts:
        path = path/part
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise Invalid(f"UNSAFE_PATH: symlink/junction {path}")
    if not path.is_relative_to(root):
        raise Invalid(f"UNSAFE_PATH: escapes repository {rel}")
    return path


def digest(path):
    return sha(path.read_bytes()) if path.is_file() else None


def durable(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name+".tmp-"+uuid.uuid4().hex)
    with tmp.open("xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    if os.name != "nt":
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


class Store:
    def __init__(self, root, count=10, budget=512*1024*1024, headroom=4*1024*1024):
        self.root = Path(root).resolve()
        self.state = safe(self.root, "translation-work/.state")
        self.txns = safe(self.root, "translation-work/.state/transactions")
        self.count, self.budget, self.headroom = count, budget, headroom
        if count < 1 or budget < 1024:
            raise Invalid("Retention must allow at least one transaction and 1024 bytes")

    @contextlib.contextmanager
    def lock(self):
        self.state.mkdir(parents=True, exist_ok=True)
        path = safe(self.root, "translation-work/.state/operation.lock")
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise Invalid("LOCKED: another operation or interrupted process; inspect status and recover --break-lock")
        token = uuid.uuid4().hex
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "token": token}, f)
                f.flush()
                os.fsync(f.fileno())
            yield
        finally:
            if path.exists() and read_json(path).get("token") == token:
                path.unlink()

    def break_lock(self):
        path = self.state/"operation.lock"
        if not path.exists():
            return
        pid = read_json(path)["pid"]
        if os.name == "nt":
            import ctypes
            k = ctypes.windll.kernel32
            k.OpenProcess.restype = ctypes.c_void_p
            k.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            k.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = k.OpenProcess(0x1000, False, pid)
            active = False
            if handle:
                code = ctypes.c_ulong()
                active = not k.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
                k.CloseHandle(handle)
            elif k.GetLastError() != 87:  # invalid PID is the only safe absence
                raise Invalid("Cannot establish that lock owner has exited")
        else:
            try:
                os.kill(pid, 0)
                active = True
            except ProcessLookupError:
                active = False
            except PermissionError:
                active = True
        if active:
            raise Invalid(f"LOCKED: owner PID {pid} is still alive")
        path.unlink()

    def receipts(self):
        result = []
        if not self.txns.exists():
            return result
        for folder in sorted(self.txns.iterdir()):
            safe(self.root, folder.relative_to(self.root).as_posix())
            if not folder.is_dir():
                raise Invalid(f"Unexpected transaction file {folder}")
            if not (folder/"receipt.json").exists():
                raise Invalid(f"INCOMPLETE_STAGING: inspect {folder}; no live promotion was authorized")
            data = (folder/"receipt.json").read_bytes()
            if (folder/"receipt.sha256").read_text().strip() != sha(data):
                raise Invalid(f"CORRUPT_RECEIPT: {folder.name}")
            receipt = json.loads(data)
            if receipt["id"] != folder.name:
                raise Invalid("Receipt ownership mismatch")
            for item in receipt["files"]:
                safe(self.root, item["path"])
                if item["before"] is not None:
                    backup = folder/item["slot"]
                    safe(self.root, backup.relative_to(self.root).as_posix())
                    staged = (folder/"ready").exists() or (folder/"complete").exists()
                    if (staged or backup.exists()) and digest(backup) != item["before"]:
                        raise Invalid(f"CORRUPT_BACKUP: {folder.name}/{item['slot']}")
            # Never recurse through links, even in an apparently completed snapshot.
            for base, dirs, files in os.walk(folder, followlinks=False):
                for name in dirs+files:
                    safe(self.root, (Path(base)/name).relative_to(self.root).as_posix())
            size = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
            complete = (folder/"complete").is_file()
            result.append((folder, receipt, size, complete))
        return result

    def clean_state(self):
        if any(not complete for _, _, _, complete in self.receipts()):
            raise Invalid("RECOVERY_REQUIRED: run recover before other writes")

    def stats(self):
        rs = self.receipts()
        completed = sum(v[3] for v in rs)
        return {"transactions": len(rs), "completed": completed,
                "protected": len(rs)-completed, "bytes": sum(v[2] for v in rs),
                "retention_count": self.count, "retention_bytes": self.budget,
                "reclaimable_bytes": sum(v[2] for v in self.gc_plan(rs)) if completed == len(rs) else 0}

    def gc_plan(self, rs=None):
        rs = self.receipts() if rs is None else rs
        if any(not v[3] for v in rs):
            raise Invalid("RECOVERY_REQUIRED: gc preserves all snapshots until recovery")
        total = sum(v[2] for v in rs)
        number = len(rs)
        selected = []
        for item in rs[:-1]:  # always retain the most recent recoverable state
            if number <= self.count and total <= self.budget:
                break
            selected.append(item)
            total -= item[2]
            number -= 1
        if number and total > self.budget:
            raise Invalid("RETENTION_BUDGET: sole recoverable snapshot exceeds configured bytes")
        return selected

    def gc(self, dry=False):
        selected = self.gc_plan()
        result = [{"id": p.name, "bytes": n, "status": "completed",
                   "age_seconds": int(time.time()-r["created"])} for p, r, n, _ in selected]
        if not dry:
            for p, _, _, _ in selected:
                # Revalidate ownership and paths immediately before deletion.
                self.receipts()
                shutil.rmtree(p)
        return result

    @staticmethod
    def new_id():
        return f"{time.time_ns():020d}-{uuid.uuid4().hex[:12]}"

    def commit(self, changes, expected=None, operation="apply", crash_after=None, transaction_id=None):
        self.clean_state()
        self.gc(dry=False)
        expected = expected or {}
        for rel, fingerprint in expected.items():
            if digest(safe(self.root, rel)) != fingerprint:
                raise Invalid(f"CONCURRENT_EDIT: {rel}")
        changed = {}
        before = {}
        for rel, value in changes.items():
            path = safe(self.root, rel)
            raw = path.read_bytes() if path.is_file() else None
            if raw != value:
                changed[rel], before[rel] = value, raw
        if not changed:
            return None
        needed = sum(len(before[k] or b"")+len(v or b"") for k, v in changed.items())+16384
        if needed > self.budget:
            raise Invalid(f"RETENTION_BUDGET: operation requires at least {needed} bytes")
        if shutil.disk_usage(self.root).free < needed+self.headroom:
            raise Invalid(f"INSUFFICIENT_SPACE: need {needed+self.headroom} free bytes before staging")
        # Verify no transient budget overshoot; reclaim only completed snapshots,
        # always leaving the latest rollback until a new transaction is verified.
        rs = self.receipts()
        while rs and sum(v[2] for v in rs)+needed > self.budget:
            if len(rs) <= 1:
                raise Invalid("RETENTION_BUDGET: increase budget; latest rollback must be retained during commit")
            shutil.rmtree(rs[0][0])
            rs = self.receipts()
        txid = transaction_id or self.new_id()
        if not re.fullmatch(r"\d{20}-[0-9a-f]{12}", txid):
            raise Invalid("Unsafe transaction identity")
        folder = self.txns/txid
        folder.mkdir(parents=True)
        receipt = {"id": txid, "operation": operation, "created": time.time(), "files": []}
        for i, (rel, value) in enumerate(changed.items()):
            slot = f"before-{i:06d}.bin"
            receipt["files"].append({"path": rel, "slot": slot,
                                      "before": sha(before[rel]) if before[rel] is not None else None,
                                      "after": sha(value) if value is not None else None})
        raw = json_bytes(receipt)
        durable(folder/"receipt.json", raw)
        durable(folder/"receipt.sha256", sha(raw).encode())
        for i, (rel, value) in enumerate(changed.items()):
            if before[rel] is not None:
                durable(folder/f"before-{i:06d}.bin", before[rel])
            if value is not None:
                durable(folder/f"after-{i:06d}.bin", value)
        durable(folder/"ready", b"all backups and staged writes durable\n")
        for rel, fingerprint in expected.items():
            if digest(safe(self.root, rel)) != fingerprint:
                # No live files changed. Complete this cancelled receipt as a
                # protected recoverable no-op, preserving the editor's changes.
                durable(folder/"cancelled", b"concurrent edit\n")
                durable(folder/"complete", b"cancelled\n")
                raise Invalid(f"CONCURRENT_EDIT: {rel}; no promotion")
        for i, item in enumerate(receipt["files"]):
            path = safe(self.root, item["path"])
            if digest(path) != item["before"]:
                raise Invalid(f"CONCURRENT_EDIT: {item['path']}; recover required")
            if item["after"] is None:
                path.unlink(missing_ok=True)
            else:
                durable(path, (folder/f"after-{i:06d}.bin").read_bytes())
            if crash_after is not None and i+1 == crash_after:
                raise Invalid("SIMULATED_CRASH: promotion interrupted")
        if any(digest(safe(self.root, f["path"])) != f["after"] for f in receipt["files"]):
            raise Invalid("Verification failed after promotion; recover required")
        durable(folder/"complete", b"verified\n")
        for p in folder.glob("after-*.bin"):
            p.unlink()
        self.gc()
        return txid

    def recover(self):
        rs = self.receipts()
        done = []
        for folder, receipt, _, complete in rs:
            if complete:
                continue
            if not (folder/"ready").exists():
                if any(digest(safe(self.root, f["path"])) != f["before"] for f in receipt["files"]):
                    raise Invalid("Unexpected live edit during incomplete staging; preserving journal")
                shutil.rmtree(folder)  # no promotion was ever authorized
                done.append(folder.name)
                continue
            self._restore(folder, receipt)
            durable(folder/"complete", b"recovered\n")
            for p in folder.glob("after-*.bin"):
                p.unlink()
            done.append(folder.name)
        return done

    def _restore(self, folder, receipt):
        # Prevalidate every live member before touching any, including deletions.
        for item in receipt["files"]:
            if digest(safe(self.root, item["path"])) not in {item["before"], item["after"]}:
                raise Invalid(f"CONCURRENT_EDIT: cannot restore {item['path']}; preserve external edits")
        for item in reversed(receipt["files"]):
            path = safe(self.root, item["path"])
            if item["before"] is None:
                path.unlink(missing_ok=True)
            else:
                durable(path, (folder/item["slot"]).read_bytes())

    def rollback(self):
        self.clean_state()
        rs = self.receipts()
        if not rs:
            raise Invalid("No retained transaction to roll back")
        folder, receipt, _, _ = rs[-1]
        if (folder/"cancelled").exists() or (folder/"complete").read_bytes() != b"verified\n":
            raise Invalid("Latest receipt was cancelled/recovered; inspect before rollback")
        expected = {v["path"]: v["after"] for v in receipt["files"]}
        changes = {v["path"]: ((folder/v["slot"]).read_bytes() if v["before"] is not None else None)
                   for v in receipt["files"]}
        return self.commit(changes, expected, operation="rollback")
