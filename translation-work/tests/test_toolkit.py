import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import release
from github_mock import GitHubMock
from native import Invalid, patch_workbook
from storage import Store, canonical, json_bytes, sha
from toolkit import BATCHES, BUILD, DIST, MANIFEST, SOURCE, Project, doctor, inventory, jsonl, make_manifest, mapped

HERE = Path(__file__).resolve().parents[1]


class Fixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.p = Project(self.root)
        self.write(".gitattributes", b"EN/** -text\nPTBR/** -text\ntranslation-work/distribution/** -text\n")
        self.write(".gitignore", b"translation-work/.state/\n")
        self.write(SOURCE + "Text/help.txt", b"@key\r\nFire\r\n")
        self.write(SOURCE + "lang.ini", b"name=English\n")
        for name in ("package.xml", "preview.jpg", "lang.ini"):
            self.write(DIST + name, (HERE / "distribution" / name).read_bytes())
        self.receipt({})
        self.row = {**list(mapped(self.root / SOURCE))[0][1], "PTBR": "Fogo", "fallback": False}
        self.batch = "batch-0001.jsonl"
        self.save_batches({self.batch: [self.row]})

    def receipt(self, files):
        manifest = json_bytes({"files": files})
        self.write("translation-work/toolchain.json", manifest)
        self.write("translation-work/runtime-support.json", json_bytes({
            "toolchain_sha256": sha(manifest), "dependencies": {"openpyxl": "3.1.5", "et-xmlfile": "2.0.0"}}))

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def save_batches(self, batches):
        for b, rows in batches.items():
            self.write(BATCHES + b, jsonl(rows))
        self.write(MANIFEST, json_bytes(make_manifest(batches, inventory(self.root, SOURCE), "EA 23.352")))

    def change(self, row, text):
        payload = self.write("edits.json", json_bytes([{"id": row["id"], "PTBR": text,
                                                        "revision": sha(json_bytes(row))}]))
        result = self.p.apply(payload)
        payload.unlink()
        row["PTBR"] = text
        return result

    def test_build_gate_and_zip(self):
        self.change(self.row, "")
        with self.assertRaisesRegex(Invalid, "INCOMPLETE"):
            self.p.build()
        self.assertFalse((self.root / "PTBR").exists())
        self.write(BUILD, b'{"complete":true}')
        with self.assertRaisesRegex(Invalid, "STALE_OR_INCOMPLETE"):
            self.p.verify_output()
        self.change(self.row, "Fogo")
        receipt = self.p.build()
        self.assertEqual(self.p.verify_output(), receipt)
        with ZipFile(io.BytesIO(self.p.archive())) as z:
            self.assertEqual(set(z.namelist()), {"package.xml", "preview.jpg", "Lang/PTBR/lang.ini",
                                                "Lang/PTBR/Text/help.txt"})
            self.assertEqual(z.read("Lang/PTBR/Text/help.txt"), b"@key\r\nFogo\r\n")
        self.write("PTBR/Lang/PTBR/Text/help.txt", b"tampered")
        with self.assertRaisesRegex(Invalid, "OUTPUT_HASH"):
            self.p.verify_output()
        self.p.build()
        self.change(self.row, "Chama")
        with self.assertRaisesRegex(Invalid, "STALE"):
            self.p.verify_output()

    def test_update_noop_preview_and_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "EN"
            shutil.copytree(self.root / SOURCE, source)
            original = (self.root / MANIFEST).stat().st_mtime_ns
            self.assertEqual(self.p.update(source, "EA 23.352", False)["files"], 0)
            self.assertEqual((self.root / MANIFEST).stat().st_mtime_ns, original)
            (source / "Text/help.txt").write_bytes(b"@different_key\r\nFire\r\n")
            result = self.p.update(source, "EA 23.355", True)
            self.assertEqual(result["review_positional"], 1)
            self.assertEqual((self.root / MANIFEST).stat().st_mtime_ns, original)
            self.p.update(source, "EA 23.355", False)
            row = self.p.load()[2][0]
            self.assertEqual(row["PTBR"], "")
            self.assertEqual(row["history"][0]["PTBR"], "Fogo")
            self.assertFalse((self.root / "PTBR").exists())
            self.p.store.rollback()
            self.assertEqual(self.p.load()[2][0]["PTBR"], "Fogo")

    def test_scale_500_changes_across_101_batches(self):
        batches = {}
        for i in range(101):
            row = {**self.row, "id": f"fixture-{i}"}
            batches[f"batch-{i+1:04}.jsonl"] = [row]
        self.save_batches(batches)
        untouched = self.root / BATCHES / "batch-0101.jsonl"
        before = untouched.stat().st_mtime_ns, untouched.read_bytes()
        for i in range(500):
            name = f"batch-{i % 100 + 1:04}.jsonl"
            self.change(batches[name][0], "Fogo" + "!" * (i // 100 + 1))
            store = self.p.store
            latest = store.receipts()[-1][1]
            self.assertEqual([f["path"] for f in latest["files"]], [BATCHES + name])
            stats = store.stats()
            self.assertLessEqual(stats["completed"], 10)
            self.assertLessEqual(stats["bytes"], 512 * 1024 * 1024)
        self.assertEqual((untouched.stat().st_mtime_ns, untouched.read_bytes()), before)

    def test_gc_and_interrupted_recovery(self):
        store = Store(self.root, count=2)
        path = BATCHES + self.batch
        baseline = (self.root / path).read_bytes()
        for idx in range(4):
            store.commit({"metadata": str(idx).encode()})
        before = store.receipts()
        store.gc(dry=True)
        self.assertEqual(before, store.receipts())
        self.assertEqual(len(before), 2)
        with self.assertRaisesRegex(Invalid, "SIMULATED_CRASH"):
            store.commit({path: b"interrupt", "metadata": b"changed"}, crash_after=1)
        for dry in (True, False):
            with self.assertRaisesRegex(Invalid, "RECOVERY_REQUIRED"):
                store.gc(dry=dry)
        store.recover()
        self.assertEqual((self.root / path).read_bytes(), baseline)
        self.assertEqual((self.root / "metadata").read_bytes(), b"3")

    def test_portability_receipt(self):
        self.git("init", "-q")
        self.write(".gitattributes", b"*.json text eol=lf\nEN/** -text\n")
        path = "translation-work/engine-shapes.json"
        authored = b'{\r\n  "fixture": true\r\n}\r\n'
        self.write(path, authored)
        self.git("add", ".gitattributes", path, SOURCE + "Text/help.txt")
        self.assertEqual(self.git("show", ":" + path), canonical(authored))
        self.assertEqual(self.git("show", ":" + SOURCE + "Text/help.txt"), b"@key\r\nFire\r\n")
        self.receipt({"engine-shapes.json": sha(canonical(authored))})
        self.assertEqual(doctor(self.p, False)["fixture"], "ok")
        self.write(path, authored.replace(b"true", b"false"))
        with self.assertRaisesRegex(Invalid, "TOOLCHAIN_HASH"):
            doctor(self.p, False)
        self.write(path, canonical(authored))
        self.write(SOURCE + "Text/help.txt", b"bad")
        with self.assertRaisesRegex(Invalid, "SOURCE_HASH"):
            doctor(self.p, False)

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], stderr=subprocess.DEVNULL)

    def commit(self):
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD").decode().strip()

    def test_release_http_end_to_end(self):
        self.write("Portrait/example.png", b"portrait fixture")
        self.p.build()
        self.git("init", "-qb", "main")
        self.write("LICENSE", b"license fixture")
        head = self.commit()
        server = GitHubMock(head)
        client = release.Client("test-token", transport=server.transport, sleeper=lambda _: None)
        server.statuses = [503, 200]
        server.fail_upload = True
        with self.assertRaisesRegex(Invalid, "GITHUB_HTTP_403"):
            release.publish(self.p, client, head)
        self.assertTrue(server.releases[0]["draft"])
        server.fail_upload = False
        self.assertEqual(release.publish(self.p, client, head)["tag"], "v1.0.0")
        self.assertEqual(release.publish(self.p, client, head)["status"], "unchanged")
        self.assertEqual({x["name"] for x in server.releases[0]["assets"]}, release.ASSET_NAMES)
        self.assertIn("https://discord.gg/uFEwSMwUYb", server.releases[0]["body"])
        self.change(self.row, "Chama")
        self.p.build()
        head = server.head = self.commit()
        self.assertEqual(release.publish(self.p, client, head)["tag"], "v1.0.1")
        self.assertIn("Livros, ajuda e documentos", server.releases[1]["body"])
        self.assertIn("/compare/", server.releases[1]["body"])
        server.releases[1]["assets"].append({"name": "LICENSE"})
        with self.assertRaisesRegex(Invalid, "Unexpected public"):
            release.publish(self.p, client, head)
        server.head = "0" * 40
        with self.assertRaisesRegex(Invalid, "STALE_COMMIT"):
            release.publish(self.p, client, head)


class Native(unittest.TestCase):
    def test_dialogue_identity_and_role_evidence(self):
        from openpyxl import Workbook
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "Dialog/Drama/scene.xlsx"
            f.parent.mkdir(parents=True)

            def write(rows):
                book = Workbook()
                sheet = book.active
                sheet.title = "ScriptJessica"
                sheet.append(["step", "actor", "if", "id", "text_EN", "text"])
                for row in rows:
                    sheet.append(row)
                book.save(f)

            scene = ["arrival", "Speaker_Jessica", None, None, None, None]
            lines = [
                [None, None, None, "self", "I am ready.", None],
                [None, None, None, "other", "Daniel is ready.", None],
                [None, "player", "selected_character", "dynamic", "Are you ready?", None],
            ]
            write([scene, *lines])
            rows = {u["anchor"]: u for _, u in mapped(root)}
            self.assertEqual(rows["self"]["context"]["last_actor_token"], "Speaker_Jessica")
            self.assertEqual(rows["other"]["gender"]["referent"], "unknown")
            self.assertEqual(rows["dynamic"]["context"]["native_fields"]["if"], "selected_character")
            self.assertEqual(rows["dynamic"]["gender"]["addressee"], "unknown")
            write([scene, [None] * 6, *lines])
            moved = {u["anchor"]: u for _, u in mapped(root)}
            self.assertEqual(moved["self"]["id"], rows["self"]["id"])
            self.assertEqual(moved["self"]["context"], rows["self"]["context"])
            self.assertNotEqual(moved["self"]["row"], rows["self"]["row"])

    def test_workbook_members_and_missing_cells(self):
        from openpyxl import Workbook, load_workbook
        b = Workbook()
        b.active.append(["id", "name", "name_EN", "formula"])
        b.active.append(["item", None, "Fire", "=1+1"])
        data = io.BytesIO()
        b.save(data)
        raw = data.getvalue()
        self.assertEqual(patch_workbook(raw, {}), raw)
        updated = patch_workbook(raw, {"Sheet": {"B2": "=Coração & ação"}})
        b = load_workbook(io.BytesIO(updated))
        self.assertEqual(b.active["B2"].value, "=Coração & ação")
        self.assertEqual(b.active["B2"].data_type, "s")
        self.assertEqual(b.active["D2"].value, "=1+1")
        with ZipFile(io.BytesIO(raw)) as before, ZipFile(io.BytesIO(updated)) as after:
            self.assertEqual(before.namelist(), after.namelist())
            for name in before.namelist():
                if name != "xl/worksheets/sheet1.xml":
                    self.assertEqual(before.read(name), after.read(name))
        with self.assertRaisesRegex(Invalid, "FORMULA_TARGET"):
            patch_workbook(raw, {"Sheet": {"D2": "bad"}})


if __name__ == "__main__":
    unittest.main()
