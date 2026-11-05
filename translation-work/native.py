from __future__ import annotations

import re
from pathlib import Path

DIRECT_DATA = {"Name.xlsx", "chara_talk.xlsx", "god_talk.xlsx"}
KEY_COLS = {"id", "k", "version", "filter", "tag", "chance", "n", "N"}
DIRECTIVE_RE = re.compile(r"^\s*[@%#]")  # @speaker bindings, %/% markers, #anchors
TOKEN_RE = re.compile(r"\{[^{}]*\}|#[A-Za-z][A-Za-z0-9_]*|#\d+|\\[nN]|[+][A-Z]+\b")


def token_set(text: str) -> list[str]:
    # normalized like validate.tokens: '#word' placeholders collapse to '#'
    return sorted(re.sub(r"^#[A-Za-z][A-Za-z0-9_]*$", "#", tok) for tok in TOKEN_RE.findall(text or ""))


def is_translatable_line(line: str) -> bool:
    if not line.strip():
        return False
    if DIRECTIVE_RE.match(line):
        return False
    return True


def make_unit(file: str, kind: str, source: str, **meta) -> dict:
    unit_id = meta.pop("unit_id")
    return {
        "id": unit_id,
        "file": file,
        "kind": kind,  # xlsx_pair | data_cell | txt_line
        "source": source,
        "tokens": token_set(source),
        **meta,
    }


def xlsx_units(rel: Path, abs_path: Path) -> list[dict]:
    units: list[dict] = []
    import openpyxl

    wb = openpyxl.load_workbook(abs_path, read_only=False)
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        headers = [c.value for c in ws[1]]
        if headers and (headers[0] == "k" or rel.parts[0] == "Data" and rel.name in DIRECT_DATA):
            # Data-style sheet: English content in value columns, key column kept
            for row in range(3, ws.max_row + 1):
                for col_idx, header in enumerate(headers):
                    if header is None or header in KEY_COLS:
                        continue
                    cell = ws.cell(row=row, column=col_idx + 1)
                    if cell.value and str(cell.value).strip():
                        units.append(
                            make_unit(
                                rel.as_posix(),
                                "data_cell",
                                str(cell.value),
                                unit_id=f"{rel.as_posix()}::{sheet_name}::{cell.coordinate}",
                                sheet=sheet_name,
                                cell=cell.coordinate,
                                field=header,
                                **({"anchor": str(ws.cell(row=row, column=1).value)}
                                   if rel.name in {"chara_talk.xlsx", "god_talk.xlsx"} else {}),
                            )
                        )
            continue
        pairs = []
        id_col = None
        for col_idx, header in enumerate(headers):
            if header is None:
                continue
            h = str(header)
            if h == "id":
                id_col = col_idx
            if h.endswith("_EN") and h[:-3] in [str(x) for x in headers if x]:
                target = headers.index(h[:-3])
                pairs.append((col_idx, target, h[:-3]))
        if not pairs:
            continue
        context_columns = {name: headers.index(name) + 1 for name in ("step", "jump", "if", "action", "param", "actor")
                           if rel.parts[0] == "Dialog" and name in headers}
        scene = None
        actor_setup = None
        for row in range(2, ws.max_row + 1):
            evidence = {key: str(ws.cell(row=row, column=col).value)
                        for key, col in context_columns.items() if ws.cell(row=row, column=col).value is not None}
            if "step" in evidence:
                scene = evidence["step"]
                actor_setup = None
            if "actor" in evidence:
                actor_setup = evidence["actor"]
            context = ({"scene": scene, "native_fields": evidence, "last_actor_token": actor_setup}
                       if context_columns else {})
            anchor = ws.cell(row=row, column=id_col + 1).value if id_col is not None else None
            if not anchor:
                continue
            for src_col, tgt_col, field in pairs:
                source = ws.cell(row=row, column=src_col + 1).value
                if source and str(source).strip():
                    units.append(
                        make_unit(
                            rel.as_posix(),
                            "xlsx_pair",
                            str(source),
                            unit_id=f"{rel.as_posix()}::{sheet_name}::R{row}C{tgt_col + 1}",
                            sheet=sheet_name,
                            row=row,
                            target_col=tgt_col + 1,
                            field=field,
                            anchor=str(anchor),
                            **({"native_context": context} if context else {}),
                        )
                    )
    wb.close()
    return units


def txt_units(rel: Path, abs_path: Path) -> list[dict]:
    units = []
    text = abs_path.read_bytes().decode("utf-8")
    lines = text.split("\n")
    for i, line in enumerate(lines):
        biography = rel.as_posix() == "Text/Background/_default.txt" and i == 0 and line.startswith("#name,")
        if biography or is_translatable_line(line.rstrip("\r")):
            units.append(
                make_unit(
                    rel.as_posix(),
                    "txt_line",
                    line.rstrip("\r"),
                    unit_id=f"{rel.as_posix()}::L{i + 1}",
                    line=i + 1,
                )
            )
    return units



# Public errors and deployment contract shared by storage and release tooling.
class Invalid(ValueError):
    pass


DEPLOY = "Lang/PTBR"


def extract(root):
    import warnings

    units = []
    with warnings.catch_warnings():
        # Reading values does not serialize unsupported workbook extensions.
        warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root)
            if path.is_file() and path.suffix == ".xlsx":
                units.extend(xlsx_units(rel, path))
            elif path.is_file() and path.suffix == ".txt":
                units.extend(txt_units(rel, path))
    return units


def patch_workbook(raw, updates):
    """Replace only addressed cells. Keep all unrelated OOXML members byte-exact."""
    from io import BytesIO
    import posixpath
    from xml.etree import ElementTree as ET
    from xml.sax.saxutils import escape
    from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rel = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    if not updates:
        return raw
    output = BytesIO()
    with ZipFile(BytesIO(raw)) as original, ZipFile(output, "w", ZIP_DEFLATED) as target:
        links = {r.attrib["Id"]: r.attrib["Target"]
                 for r in ET.fromstring(original.read("xl/_rels/workbook.xml.rels"))}
        sheets = {}
        for sheet in ET.fromstring(original.read("xl/workbook.xml")).findall(f"{ns}sheets/{ns}sheet"):
            name = links[sheet.attrib[rel+"id"]]
            sheets[sheet.attrib["name"]] = name.lstrip("/") if name.startswith("/") else posixpath.normpath("xl/"+name)
        edits = {sheets[name]: cells.copy() for name, cells in updates.items()}
        for name in original.namelist():
            content = original.read(name)
            if name in edits:
                cells = edits.pop(name)

                def inline(start, value):
                    start = re.sub(rb'\s+t="[^"]*"', b"", start)
                    if value == "":
                        return start + b"/>"
                    body = escape(value).replace("\r", "&#13;").encode("utf-8")
                    return start + b' t="inlineStr"><is><t xml:space="preserve">' + body + b"</t></is></c>"

                def replace(match):
                    start = match.group(1)
                    coordinate = re.search(rb'\br="([A-Z]+[0-9]+)"', start)
                    if not coordinate or coordinate[1].decode() not in cells:
                        return match[0]
                    value = cells.pop(coordinate[1].decode())
                    if b"<f" in match[0]:
                        raise Invalid(f"FORMULA_TARGET: {coordinate[1].decode()}")
                    return inline(start, value)

                cell_pattern = rb'(<c\s+[^<>]*?)(?:\s*/>|>.*?</c>)'
                content = re.sub(cell_pattern, replace, content, flags=re.S)
                if cells:
                    from openpyxl.utils.cell import coordinate_to_tuple
                    by_row = {}
                    for coord, value in cells.items():
                        if value:
                            row, col = coordinate_to_tuple(coord)
                            by_row.setdefault(row, {})[col] = (coord, value)

                    def insert_missing(match):
                        start, body = match.groups()
                        number = re.search(rb'\br="([0-9]+)"', start)
                        pending = by_row.pop(int(number[1]), {}) if number else {}
                        if not pending:
                            return match[0]
                        for existing in re.finditer(cell_pattern, body, flags=re.S):
                            coord = re.search(rb'\br="([A-Z]+[0-9]+)"', existing[1])
                            if coord:
                                _, col = coordinate_to_tuple(coord[1].decode())
                                pending[col] = existing[0]
                        if re.sub(cell_pattern, b"", body, flags=re.S).strip():
                            raise Invalid(f"OOXML_UNSUPPORTED_ROW: {name} row {number[1].decode()}")
                        ordered = []
                        for item in (pending[i] for i in sorted(pending)):
                            if isinstance(item, bytes):
                                ordered.append(item)
                            else:
                                coord, value = item
                                ordered.append(inline(b'<c r="' + coord.encode() + b'"', value))
                        return start + b">" + b"".join(ordered) + b"</row>"

                    content = re.sub(rb'(<row\s+[^<>]*?)>(.*?)</row>', insert_missing, content, flags=re.S)
                    if by_row:
                        raise Invalid(f"OOXML_MISSING_ROWS: {name}: {list(by_row)[:8]}")
                ET.fromstring(content)
            target.writestr(ZipInfo(name), content, compress_type=ZIP_DEFLATED)
        if edits:
            raise Invalid(f"OOXML_MISSING_SHEETS: {list(edits)}")
    return output.getvalue()


def patch_text(raw, updates, insert=b""):
    if not updates and not insert:
        return raw
    lines = raw.split(b"\n")
    for number, value in updates.items():
        original = lines[number - 1]
        newline = b"\r" if original.endswith(b"\r") else b""
        bom = b"\xef\xbb\xbf" if number == 1 and original.startswith(b"\xef\xbb\xbf") else b""
        lines[number - 1] = bom + value.encode("utf-8") + newline
    if insert:
        # Original translated notice precedes the update heading.
        if not lines[12].startswith(b"{topic,"):
            raise Invalid("VERSION_NOTICE_ANCHOR: expected the update topic on line 13")
        lines.insert(11, insert.removesuffix(b"\n"))
    return b"\n".join(lines)
