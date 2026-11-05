"""One-time import from the preserved private Elin workspace."""
from collections import Counter
from pathlib import Path
import argparse
import json
import warnings

from openpyxl import load_workbook
from toolkit import (BATCHES, MANIFEST, SIZE, SOURCE, Invalid, Project, cell, check_unit,
                     inventory, json_bytes, jsonl, make_manifest, mapped, records, sha)


def migrate(root, old):
    project = Project(root)
    source = project.path(SOURCE.rstrip("/"))
    target = old / "EN/Package/PTBR/Lang/PTBR"
    queue = {u["id"]: u for u in records(old / "work/queue.jsonl")}
    batch_values = {}
    for batch in sorted((old / "work/translations").glob("batch_*.json")):
        batch_values.update(json.loads(batch.read_text(encoding="utf-8")))
    if set(queue) != set(batch_values):
        raise Invalid("LEGACY_BATCH_INVENTORY_MISMATCH")
    cache = {}
    rows = []
    counts = Counter()
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
        for legacy, unit in mapped(source):
            if legacy in queue and queue[legacy]["source"] != unit["EN"]:
                raise Invalid(f"LEGACY_SOURCE_MISMATCH: {legacy}")
            name = unit["file"]
            if name not in cache:
                path = target / name
                cache[name] = (load_workbook(path) if name.endswith(".xlsx")
                               else path.read_text(encoding="utf-8").split("\n"))
            native = cache[name]
            if unit["kind"] == "txt_line":
                number = unit["line"]
                if name == "Text/version.txt" and number >= 13:
                    number += 9
                pt = native[number-1]
            else:
                pt = native[unit["sheet"]][cell(unit)].value or ""
            if not isinstance(pt, str):
                raise Invalid(f"LEGACY_NON_STRING: {legacy}")
            if legacy not in queue:
                counts["supplemental"] += 1
            elif pt != batch_values[legacy]:
                counts["native_differences"] += 1
            unit.update(PTBR=pt, fallback=False)
            if not pt:
                unit["fallback"] = check_unit(unit["EN"], "")[0]
                counts["fallback" if unit["fallback"] else "pending"] += 1
            elif not check_unit(unit["EN"], pt)[0]:
                if legacy in queue:
                    raise Invalid(f"LEGACY_INVALID_TRANSLATION: {legacy}")
                unit["imported_validation_sha256"] = sha(json_bytes([unit["EN"], pt]))
                counts["legacy_exceptions"] += 1
            rows.append(unit)
    if len(rows) - counts["supplemental"] != len(queue):
        raise Invalid("LEGACY_QUEUE_COUNT_MISMATCH")
    batches = {f"batch-{i // SIZE + 1:04d}.jsonl": rows[i:i+SIZE] for i in range(0, len(rows), SIZE)}
    manifest = make_manifest(batches, inventory(root, SOURCE), "EA 23.352")
    with project.store.lock():
        expected = project.work_receipts() if project.path(MANIFEST).exists() else {}
        if expected:
            previous, _, existing = project.load()
            candidate = {r["id"]: r for r in rows}
            if previous["sources"] != manifest["sources"] or any(candidate.get(r["id"]) != r for r in existing):
                raise Invalid("MIGRATION_WOULD_OVERWRITE_EXISTING_WORK")
        project.store.commit({MANIFEST: json_bytes(manifest),
                              **{BATCHES + n: jsonl(batch) for n, batch in batches.items()}},
                             expected=expected, operation="migration")
    print(json.dumps({"entries": len(rows), "batches": len(batches), **counts}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("private_workspace", type=Path)
    args = parser.parse_args()
    migrate(Path(__file__).resolve().parent.parent, args.private_workspace)
