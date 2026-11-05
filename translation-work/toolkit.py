"""Transactional, offline Elin localization toolkit."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import nullcontext
from io import BytesIO
import json
from pathlib import Path
import platform
import re
import sys
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo

sys.dont_write_bytecode = True
from native import DEPLOY, Invalid, extract, patch_text, patch_workbook
from storage import Store, canonical, digest, json_bytes, read_json, safe, sha
from validate import check_unit, tokens

WORK = "translation-work/"
BATCHES = WORK + "translations/"
MANIFEST = BATCHES + "manifest.json"
BUILD = WORK + "build-manifest.json"
SOURCE = "EN/Package/Lang/EN/"
DIST = WORK + "distribution/"
SIZE = 500
GAME = Path("G:/SteamLibrary/steamapps/common/Elin")


def jsonl(rows):
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows).encode("utf-8")


def records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def inventory(root, prefix):
    base = safe(root, prefix.rstrip("/"))
    result = {}
    for path in sorted(base.rglob("*")):
        rel = path.relative_to(root).as_posix()
        safe(root, rel)
        if path.is_file():
            result[rel.removeprefix(prefix)] = sha(path.read_bytes())
    return result


def cell(unit):
    if unit["kind"] == "data_cell":
        return unit["cell"]
    column = unit["target_col"]
    name = ""
    while column:
        column, digit = divmod(column - 1, 26)
        name = chr(65 + digit) + name
    return name + str(unit["row"])


def mapped(root):
    units = extract(root)
    keys = Counter((u["file"], u.get("sheet"), u.get("anchor"), u.get("field")) for u in units)
    for u in units:
        legacy_id = u.pop("id")
        key = u["file"], u.get("sheet"), u.get("anchor"), u.get("field")
        keyed = u.get("anchor") is not None and keys[key] == 1
        u["id"] = json.dumps(key, ensure_ascii=False, separators=(",", ":")) if keyed else legacy_id
        u["source_file"] = u["file"]
        u["EN"] = u.pop("source")
        u["tokens"] = tokens(u["EN"])
        u["gender"] = {"speaker": "unknown", "addressee": "unknown", "referent": "unknown"}
        if u["file"].startswith("Dialog/"):
            u["context"] = {"dialogue_file": u["file"], "sheet": u.get("sheet"),
                            "native_row_key": u.get("anchor"), "agreement": "review",
                            **u.pop("native_context", {})}
        yield legacy_id, u


def metadata(row):
    return {k: v for k, v in row.items() if k not in {"PTBR", "fallback", "history"}}


def value(row):
    return row["PTBR"]


def validate(row):
    pt = row["PTBR"]
    if pt == "":
        if type(row.get("fallback")) is not bool:
            raise Invalid(f"INVALID_FALLBACK: {row['id']}")
        if row["fallback"] and not check_unit(row["EN"], "")[0]:
            raise Invalid(f"INVALID_FALLBACK: {row['id']}")
        return
    if not isinstance(pt, str) or not pt.strip() or row.get("fallback") is not False:
        raise Invalid(f"INVALID_PTBR: {row['id']}")
    if row["kind"] == "txt_line" and ("\r" in pt or "\n" in pt):
        raise Invalid(f"MULTILINE_TXT: {row['id']}")
    if row["kind"] != "txt_line" and len(pt.encode("utf-16-le", errors="surrogatepass")) > 65534:
        raise Invalid(f"EXCEL_CELL_LIMIT: {row['id']}")
    if any(ord(c) in {*range(9), 11, 12, *range(14, 32), 0xFFFE, 0xFFFF} or
           0xD800 <= ord(c) <= 0xDFFF for c in pt):
        raise Invalid(f"INVALID_CONTROL: {row['id']}")
    accepted, errors = check_unit(row["EN"], pt)
    if not accepted and row.get("imported_validation_sha256") != sha(json_bytes([row["EN"], pt])):
        raise Invalid(f"{row['id']}: {'; '.join(errors)}")


class Project:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def path(self, rel):
        return safe(self.root, rel)

    @property
    def store(self):
        return Store(self.root)

    def load(self):
        manifest = read_json(self.path(MANIFEST))
        if (manifest["schema"] != 1 or len(set(manifest["batches"])) != len(manifest["batches"])
                or any(not re.fullmatch(r"batch-\d{4}\.jsonl", b) for b in manifest["batches"])):
            raise Invalid("INVALID_MANIFEST")
        if {p.name for p in self.path(BATCHES.rstrip("/")).glob("*.jsonl")} != set(manifest["batches"]):
            raise Invalid("UNTRACKED_BATCH")
        batches = {name: records(self.path(BATCHES + name)) for name in manifest["batches"]}
        rows = [row for batch in batches.values() for row in batch]
        ids = [r["id"] for r in rows]
        if len(ids) != len(set(ids)) or len(ids) != manifest["entries"]:
            raise Invalid("INVALID_BATCH_COUNT_OR_DUPLICATE_ID")
        if sha(jsonl(sorted(map(metadata, rows), key=lambda row: row["id"]))) != manifest["mapping_sha256"]:
            raise Invalid("SOURCE_MAPPING_CHANGED: restore source metadata or run update-sources")
        for row in rows:
            validate(row)
        return manifest, batches, rows

    def source_check(self, manifest):
        if inventory(self.root, SOURCE) != manifest["sources"]:
            raise Invalid("SOURCE_HASH_MISMATCH: restore EN or import a verified source export")

    def summary(self, rows):
        pending = [r for r in rows if r["PTBR"] == "" and not r["fallback"]]
        return {"entries": len(rows), "pending": len(pending),
                "translated": sum(r["PTBR"] != "" for r in rows),
                "fallback": sum(r["fallback"] for r in rows), "next": [r["id"] for r in pending[:1]]}

    def fingerprint(self, manifest):
        paths = [MANIFEST] + [BATCHES + b for b in manifest["batches"]]
        work = {p: sha(canonical(self.path(p).read_bytes())) for p in paths}
        return sha(json_bytes([work, inventory(self.root, DIST), self.integrity()]))

    def integrity(self):
        receipt = read_json(self.path(WORK + "toolchain.json"))
        runtime = read_json(self.path(WORK + "runtime-support.json"))
        if runtime["toolchain_sha256"] != sha(json_bytes(receipt)):
            raise Invalid("TOOLCHAIN_RECEIPT_MISMATCH")
        for name, digest in receipt["files"].items():
            if sha(canonical(self.path(WORK + name).read_bytes())) != digest:
                raise Invalid(f"TOOLCHAIN_HASH_MISMATCH: {name}")
        return sha(json_bytes(runtime))

    def apply(self, payload_path):
        payload = read_json(payload_path)
        if not isinstance(payload, list) or any(not isinstance(edit, dict) for edit in payload):
            raise Invalid("INVALID_PAYLOAD: expected an array of edit objects")
        with self.store.lock():
            self.store.clean_state()
            expected = self.work_receipts()
            manifest, batches, rows = self.load()
            lookup = {row["id"]: (batch, row) for batch, group in batches.items() for row in group}
            changed = set()
            seen = set()
            for edit in payload:
                uid = edit["id"]
                if uid in seen or uid not in lookup:
                    raise Invalid(f"UNKNOWN_OR_DUPLICATE_ID: {uid}")
                seen.add(uid)
                batch, row = lookup[uid]
                if edit["revision"] != sha(json_bytes(row)):
                    raise Invalid(f"STALE_REVISION: {uid}")
                after = {**row, "PTBR": edit["PTBR"], "fallback": edit.get("fallback", False)}
                if (after["PTBR"], after["fallback"]) == (row["PTBR"], row["fallback"]):
                    continue
                validate(after)
                row.clear()
                row.update(after)
                changed.add(batch)
            return self.store.commit({BATCHES + b: jsonl(batches[b]) for b in changed}, expected=expected)

    def work_receipts(self):
        return {path.relative_to(self.root).as_posix(): digest(path)
                for path in self.path(BATCHES.rstrip("/")).iterdir() if path.is_file()}

    def update(self, source, version, dry, allow_removed=()):
        with (nullcontext() if dry else self.store.lock()):
            self.store.clean_state()
            expected = self.work_receipts()
            manifest, batches, rows = self.load()
            self.source_check(manifest)
            expected.update({SOURCE + name: digest for name, digest in manifest["sources"].items()})
            if source.is_symlink() or not source.is_dir():
                raise Invalid("INVALID_EXPORT_ROOT")
            source = source.resolve()
            current = {p.relative_to(source).as_posix(): p for p in source.rglob("*") if p.is_file()}
            for name in current:
                safe(source, name)
                if (name != "lang.ini" and
                        (name.split("/")[0] not in {"Data", "Dialog", "Game", "Text", "Widget"}
                         or current[name].suffix not in {".xlsx", ".txt"})):
                    raise Invalid(f"UNSUPPORTED_EXPORT_MEMBER: {name}")
            removed = set(manifest["sources"]) - set(current)
            if set(allow_removed) - removed:
                raise Invalid("INVALID_REMOVAL: each approved path must actually be absent")
            required = removed - set(allow_removed)
            if required:
                raise Invalid(f"INCOMPLETE_EXPORT: {len(required)} missing files, e.g. {min(required)}")
            for name in removed:
                if name == "lang.ini" or not any(n.startswith(name.split("/")[0] + "/") for n in current):
                    raise Invalid(f"INCOMPLETE_EXPORT: cannot remove a whole source family: {name}")
            digests = {name: sha(p.read_bytes()) for name, p in current.items()}
            if digests == manifest["sources"] and version == manifest["version"]:
                return {"unchanged": len(rows), "files": 0}
            old = {row["id"]: row for row in rows}
            new = {}
            summary = Counter()
            diff = []
            for _, unit in mapped(source):
                uid = unit["id"]
                if uid in new:
                    raise Invalid(f"DUPLICATE_ID: {uid}")
                prior = old.get(uid)
                if prior is None:
                    action = "added"
                elif (prior["EN"], prior.get("context")) != (unit["EN"], unit.get("context")):
                    action = "changed"
                elif not uid.startswith("[") and digests[unit["file"]] != manifest["sources"].get(unit["file"]):
                    action = "review_positional"
                else:
                    action = "unchanged"
                row = {**unit, "PTBR": "", "fallback": False}
                if action == "unchanged":
                    if "imported_validation_sha256" in prior:
                        row["imported_validation_sha256"] = prior["imported_validation_sha256"]
                    row.update({k: prior[k] for k in prior if k not in metadata(prior)})
                elif prior is not None:
                    row["history"] = [*prior.get("history", []),
                                      {"EN": prior["EN"], "PTBR": prior["PTBR"], "fallback": prior["fallback"]}]
                new[uid] = row
                summary[action] += 1
                if action != "unchanged":
                    diff.append({"action": action, "id": uid, "old": prior, "new": row})
            for uid in sorted(old.keys() - new.keys()):
                summary["removed"] += 1
                diff.append({"action": "removed", "id": uid, "old": old[uid]})
            for batch, group in batches.items():
                batches[batch] = [new.pop(r["id"]) for r in group if r["id"] in new]
            extra = list(new.values())
            while extra:
                batch = f"batch-{len(batches)+1:04d}.jsonl"
                batches[batch], extra = extra[:SIZE], extra[SIZE:]
            if not dry:
                changes = {SOURCE + n: p.read_bytes() for n, p in current.items()
                           if digests[n] != manifest["sources"].get(n)}
                changes.update({SOURCE + name: None for name in removed})
                changes.update({BATCHES + b: jsonl(group) for b, group in batches.items()
                                if not self.path(BATCHES+b).is_file()
                                or canonical(self.path(BATCHES+b).read_bytes()) != jsonl(group)})
                changes[MANIFEST] = json_bytes(make_manifest(batches, digests, version))
                changes[WORK + "reports/source-diff.jsonl"] = jsonl(diff)
                if any(sha(current[n].read_bytes()) != h for n, h in digests.items()):
                    raise Invalid("CONCURRENT_EXPORT_EDIT")
                self.store.commit(changes, expected=expected, operation="update-sources")
            return {**summary, "diff": diff} if dry else dict(summary)

    def build(self, dry=False):
        with (nullcontext() if dry else self.store.lock()):
            self.store.clean_state()
            expected = self.work_receipts()
            manifest, _, rows = self.load()
            self.source_check(manifest)
            expected.update({SOURCE + name: digest for name, digest in manifest["sources"].items()})
            if self.summary(rows)["pending"]:
                raise Invalid("INCOMPLETE: finish or explicitly resolve every pending entry before build")
            fingerprint = self.fingerprint(manifest)
            updates = defaultdict(lambda: defaultdict(dict))
            text = defaultdict(dict)
            for row in rows:
                if row["kind"] == "txt_line":
                    # A blank TXT line cannot act as a cell-level fallback.
                    if not row["fallback"]:
                        text[row["file"]][row["line"]] = value(row)
                else:
                    updates[row["file"]][row["sheet"]][cell(row)] = value(row)
            package = self.path(DIST + "package.xml").read_bytes()
            version = manifest["version"].removeprefix("EA ")
            if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", version):
                raise Invalid(f"INVALID_GAME_VERSION: {manifest['version']}")
            package, count = re.subn(rb"<version>[^<]*</version>", b"<version>" + version.encode() + b"</version>", package)
            if count != 1:
                raise Invalid("PACKAGE_VERSION_FIELD: package.xml must contain one version field")
            output = {"package.xml": package,
                      "preview.jpg": self.path(DIST + "preview.jpg").read_bytes()}
            for name in manifest["sources"]:
                raw = self.path(SOURCE + name).read_bytes()
                if name == "lang.ini":
                    raw = self.path(DIST + name).read_bytes()
                elif name.endswith(".xlsx"):
                    raw = patch_workbook(raw, updates.get(name, {}))
                elif name.endswith(".txt"):
                    notice = self.path(DIST + "version-notice.txt").read_bytes() if name == "Text/version.txt" else b""
                    raw = patch_text(raw, text.get(name, {}), notice)
                output[DEPLOY + "/" + name] = raw
            receipt = {"schema": 1, "complete": True, "version": manifest["version"],
                       "fingerprint": fingerprint, "outputs": {n: sha(v) for n, v in output.items()}}
            if not dry:
                current = inventory(self.root, "PTBR/")
                expected.update({"PTBR/" + name: digest for name, digest in current.items()})
                # Preserve legacy notices under version control, outside the managed mod.
                changes = {"PTBR/" + n: None for n in current.keys() - output.keys()}
                changes.update({"PTBR/" + n: v for n, v in output.items() if current.get(n) != sha(v)})
                changes[BUILD] = json_bytes(receipt)
                if self.fingerprint(manifest) != fingerprint:
                    raise Invalid("CONCURRENT_EDIT: source or batch changed during build")
                self.store.commit(changes, expected=expected, operation="build")
            return receipt

    def verify_output(self):
        manifest, _, rows = self.load()
        self.source_check(manifest)
        receipt = read_json(self.path(BUILD))
        if (receipt.get("complete") is not True or self.summary(rows)["pending"]
                or receipt["version"] != manifest["version"] or receipt["fingerprint"] != self.fingerprint(manifest)):
            raise Invalid("STALE_OR_INCOMPLETE_OUTPUT: run complete build")
        expected = {DEPLOY + "/" + name for name in manifest["sources"]} | {"package.xml", "preview.jpg"}
        if set(receipt["outputs"]) != expected or receipt["outputs"] != inventory(self.root, "PTBR/"):
            raise Invalid("OUTPUT_HASH_MISMATCH")
        return receipt

    def archive(self):
        receipt = self.verify_output()
        data = BytesIO()
        with ZipFile(data, "w", ZIP_DEFLATED) as archive:
            for name, digest in sorted(receipt["outputs"].items()):
                content = self.path("PTBR/" + name).read_bytes()
                if sha(content) != digest:
                    raise Invalid(f"CHANGED_DURING_PACKAGING: {name}")
                archive.writestr(ZipInfo(name), content, compress_type=ZIP_DEFLATED)
        with ZipFile(data) as archive:
            if archive.testzip() or set(archive.namelist()) != set(receipt["outputs"]):
                raise Invalid("ZIP_VERIFICATION_FAILED")
        return data.getvalue()


def make_manifest(batches, sources, version):
    rows = [r for group in batches.values() for r in group]
    return {"schema": 1, "version": version, "entries": len(rows), "batches": list(batches),
            "batch_size": SIZE, "source_root": SOURCE, "deploy_root": "PTBR/" + DEPLOY + "/",
            "source_count": len(sources), "sources": sources, "mapping_sha256": sha(jsonl(sorted(map(metadata, rows), key=lambda row: row["id"])))}


def doctor(project, target):
    from importlib.metadata import PackageNotFoundError, version
    project.integrity()
    project.source_check(read_json(project.path(MANIFEST)))
    arch = platform.machine().lower()
    if target and (platform.system() != "Linux" or arch not in {"arm64", "aarch64"}
                   or platform.freedesktop_os_release().get("ID") != "ubuntu"
                   or platform.freedesktop_os_release().get("VERSION_ID") != "24.04"):
        raise Invalid(f"UNSUPPORTED_TARGET: expected Ubuntu 24.04 ARM64, found {platform.system()} {arch}")
    if sys.version_info < (3, 10):
        raise Invalid("MISSING_RUNTIME: Python 3.10+ required")
    runtime = read_json(project.path(WORK + "runtime-support.json"))
    for name, required in runtime["dependencies"].items():
        try:
            actual = version(name)
        except PackageNotFoundError as e:
            raise Invalid(f"MISSING_DEPENDENCY: {name}; install translation-work/requirements.txt in a venv") from e
        if actual != required:
            raise Invalid(f"DEPENDENCY_VERSION: {name} {actual}; expected {required}")
    from openpyxl import Workbook, load_workbook
    book = Workbook()
    book.active.append(["id", "name", "name_EN"])
    book.active.append(["fire", "original", "Fire"])
    data = BytesIO()
    book.save(data)
    native = data.getvalue()
    try:
        book = load_workbook(BytesIO(patch_workbook(native, {"Sheet": {"B2": "Coração"}})))
        if [c.value for c in book.active[2]] != ["fire", "Coração", "Fire"]:
            raise Invalid("cell values differ")
        if patch_text(b"@key\r\nFire\r\n", {2: "Coração"}) != "@key\r\nCoração\r\n".encode():
            raise Invalid("native text differs")
    except (Invalid, OSError, ValueError) as e:
        raise Invalid(f"INVALID_DOCTOR_FIXTURE: {e}") from e
    return {"runtime": sys.version.split()[0], "architecture": arch, "fixture": "ok", "read_only": True}


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd in ("status", "resume", "check", "verify-output", "rollback"):
        sub.add_parser(cmd)
    build = sub.add_parser("build")
    build.add_argument("--dry-run", action="store_true")
    apply = sub.add_parser("apply")
    apply.add_argument("payload", type=Path)
    package = sub.add_parser("package")
    package.add_argument("destination", type=Path)
    gc = sub.add_parser("gc")
    gc.add_argument("--dry-run", action="store_true")
    recover = sub.add_parser("recover")
    recover.add_argument("--break-lock", action="store_true")
    doc = sub.add_parser("doctor")
    doc.add_argument("--ubuntu-arm64", action="store_true")
    update = sub.add_parser("update-sources")
    update.add_argument("--game-root", type=Path)
    update.add_argument("--export-root", type=Path, help="Complete verified Lang/EN editable export")
    update.add_argument("--version")
    update.add_argument("--dry-run", action="store_true")
    update.add_argument("--allow-removed-file", action="append", default=[], metavar="RELATIVE_PATH")
    args = parser.parse_args()
    p = Project(Path(__file__).resolve().parent.parent)
    cmd = args.command
    try:
        if cmd in {"status", "resume", "check"}:
            manifest, _, rows = p.load()
            if cmd == "check":
                p.source_check(manifest)
                p.integrity()
            result = p.summary(rows)
            if cmd == "resume":
                result["next"] = [{**r, "revision": sha(json_bytes(r))} for r in rows
                                  if r["PTBR"] == "" and not r["fallback"]][:SIZE]
        elif cmd == "apply":
            result = p.apply(args.payload)
        elif cmd == "build":
            result = p.build(args.dry_run)
        elif cmd == "verify-output":
            result = p.verify_output()
        elif cmd == "package":
            archive = p.archive()
            with args.destination.open("xb") as f:
                f.write(archive)
            result = {"zip": str(args.destination), "sha256": sha(archive)}
        elif cmd == "doctor":
            result = doctor(p, args.ubuntu_arm64)
        elif cmd == "update-sources":
            root = args.game_root or GAME
            if args.export_root:
                if not args.version:
                    raise Invalid("EXPORT_VERSION_REQUIRED: identify the build used to export the original tables")
                source, ver = args.export_root, args.version
            else:
                if not (root / "Elin.exe").is_file() or not (root / "version.json").is_file():
                    raise Invalid("GAME_NOT_FOUND: pass --game-root to the Elin installation")
                installed = read_json(root / "version.json")
                if installed.get("demo") or installed.get("nightly") or installed.get("releaseMode") != "Public":
                    raise Invalid("UNSUPPORTED_GAME_EDITION: use a public stable installation")
                ver = installed["versionText"]
                source = root / "Package/_Elona/Lang/EN"
                if not (source / "Game").is_dir():
                    raise Invalid(f"EDITABLE_EXPORT_REQUIRED: {ver} has compiled Game tables; pass --export-root and --version")
            result = p.update(source, ver, args.dry_run, args.allow_removed_file)
        elif cmd == "gc" and args.dry_run:
            result = p.store.gc(dry=True)
        elif cmd == "recover" and args.break_lock:
            result = p.store.break_lock()
        else:
            with p.store.lock():
                result = {"gc": p.store.gc, "rollback": p.store.rollback, "recover": p.store.recover}[cmd]()
        print(json.dumps(result, ensure_ascii=True))
    except (Invalid, OSError, KeyError, ValueError, ImportError, BadZipFile) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
