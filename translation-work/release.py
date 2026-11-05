"""Verified PTBR GitHub Releases. CI invokes main; tests exercise HTTP paths."""
from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import json
import os
from pathlib import Path
import re
import subprocess
import sys
sys.dont_write_bytecode = True
import time
import urllib.error
import urllib.parse
import urllib.request

from native import Invalid, DEPLOY
from storage import json_bytes, read_json, sha
from toolkit import Project, BUILD, WORK

REPOSITORY = "isyuricunha/elin-portugues-brasileiro"
SEMVER = re.compile(r"v(\d+)\.(\d+)\.(\d+)$")


def git(root, *args, allow_failure=False):
    p = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    if p.returncode and not allow_failure:
        raise Invalid("GIT_ERROR: "+p.stderr.decode("utf-8", errors="replace"))
    return p


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Invalid("API_REDIRECT: refusing to forward credentials")


class Client:
    def __init__(self, token, repository=REPOSITORY, transport=None, sleeper=time.sleep):
        if repository != REPOSITORY:
            raise Invalid("Release publishing is restricted to the canonical repository")
        self.repository, self.token = repository, token
        self.transport, self.sleeper = transport or self.http, sleeper
        self.root = "/repos/"+repository

    def http(self, method, url, headers, body):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=60) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def request(self, method, endpoint="", data=None, missing=False, upload=False, content_type=None):
        if endpoint and not endpoint.startswith("/"):
            raise Invalid("API endpoint must be repository-relative")
        base = "https://uploads.github.com" if upload else "https://api.github.com"
        url = base+self.root+endpoint
        parsed = urllib.parse.urlparse(url)
        if parsed.hostname not in {"api.github.com", "uploads.github.com"} or parsed.scheme != "https":
            raise Invalid("Unsafe API host")
        raw = data if isinstance(data, bytes) else json_bytes(data) if data is not None else None
        headers = {"Accept": "application/vnd.github+json", "Authorization": "Bearer "+self.token,
                   "User-Agent": "Elin-PTBR-Release", "X-GitHub-Api-Version": "2022-11-28"}
        if not self.token:
            del headers["Authorization"]
        if raw is not None:
            headers["Content-Type"] = content_type or ("application/zip" if upload else "application/json")
        for attempt in range(3):
            status, response, response_headers = self.transport(method, url, headers, raw)
            if status == 404 and missing:
                return None
            if status in {429, 500, 502, 503, 504} and method == "GET" and attempt < 2:
                self.sleeper(min(2**attempt, 4))
                continue
            if not 200 <= status < 300:
                # Never print request headers or a response potentially containing secrets.
                raise Invalid(f"GITHUB_HTTP_{status}: {method} {parsed.path}; check permissions, resource access and rerun safely")
            return json.loads(response) if response else None
        raise Invalid("GITHUB_RETRY_EXHAUSTED")

    def releases(self):
        result = []
        for page in range(1, 101):
            batch = self.request("GET", f"/releases?per_page=100&page={page}")
            result.extend(batch)
            if len(batch) < 100:
                return result
        raise Invalid("Release pagination exceeds safe bound")

    def tag_sha(self, tag):
        ref = self.request("GET", "/git/ref/tags/"+urllib.parse.quote(tag, safe=""), missing=True)
        if ref is None:
            return None
        obj = ref["object"]
        for _ in range(8):
            if obj["type"] == "commit":
                return obj["sha"]
            if obj["type"] != "tag":
                break
            obj = self.request("GET", "/git/tags/"+obj["sha"])["object"]
        raise Invalid("Unsupported or cyclic tag object")


def history_rows(project, ref):
    manifest = json.loads(git(project.root, "show", f"{ref}:{WORK}translations/manifest.json").stdout)
    result = {}
    for b in manifest["batches"]:
        data = git(project.root, "show", f"{ref}:{WORK}translations/{b}").stdout
        for line in data.decode("utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row["id"] in result:
                    raise Invalid("Duplicate historic ID")
                result[row["id"]] = row
    return result


def changelog(project, previous, current, receipt):
    rows = history_rows(project, current)
    old = history_rows(project, previous) if previous else {}
    changes = {rid for rid, row in rows.items() if rid not in old or
               (row['EN'], row['PTBR'], row.get('gender')) !=
               (old[rid]['EN'], old[rid]['PTBR'], old[rid].get('gender'))}
    categories = {"Dialog": "Diálogos", "Text": "Livros, ajuda e documentos",
                  "Data": "Nomes e expressões", "Widget": "Falas de mascotes"}
    counts = {}
    for rid in changes:
        file = rows[rid]["source_file"]
        label = "Tabelas do jogo" if file.startswith("Game/") else categories.get(file.split("/")[0], "Outros textos")
        counts[label] = counts.get(label, 0) + 1
    body = (f"## Download\n\nBaixe **PTBR.zip** para instalar só a tradução ou **PTBR-COM-PORTRAIT.zip** para incluir os retratos. O pacote tem como referência Elin **{receipt['version']}**. "
            "Os arquivos Source code contêm o repositório.\n\n## O que mudou\n\n")
    if not previous:
        body += "Primeiro pacote validado pelo novo fluxo de manutenção da tradução.\n\n"
    for name, count in sorted(counts.items()):
        body += f"- **{name}** · {count} entradas incluídas ou atualizadas.\n"
    removed = len(set(old)-set(rows))
    if removed:
        body += f"- {removed} entradas removidas da fonte atual.\n"
    if not changes and not removed:
        body += "- Atualização dos arquivos do mod, sem alteração dos textos.\n"
    if previous:
        body += f"\n[Comparar versões](https://github.com/{REPOSITORY}/compare/{previous}...{current})\n"
    body += ("\n## Instalação\n\nFeche o jogo e faça backup da pasta do mod anterior. "
             "Extraia o ZIP em `Package/PTBR` na pasta do jogo. "
             "Abra o jogo e selecione Português nas configurações. "
             f"[Guia completo](https://github.com/{REPOSITORY}#instalação)\n\n"
             "## Comunidade e suporte\n\n"
             "[Vai Brasil](https://discord.gg/uFEwSMwUYb) · "
             f"[Relatar um problema](https://github.com/{REPOSITORY}/issues)\n\n"
             "Apoio voluntário via Pix `pix@yuricunha.com`.\n\n")
    return body + '<!-- ptbr-fingerprint: '+sha(json_bytes(receipt['outputs']))+' -->'


def docs_status(project, published):
    warnings = []
    if published and not published.get("draft", True):
        assets = published.get("assets", [])
        if not any(a.get("name") == "PTBR.zip" and a.get("state") == "uploaded" for a in assets):
            raise Invalid("Docs reconciliation requires a confirmed published PTBR.zip")
        for rel in ["README.md", WORK+"README.md"]:
            try:
                text = project.path(rel).read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                warnings.append({"file": rel, "claim": "missing or unreadable documentation",
                                 "action": "Restore and reconcile this document with the confirmed Release"})
                continue
            if "<!-- release-state: unavailable -->" in text:
                warnings.append({"file": rel, "claim": "release-state: unavailable",
                                 "action": f"Confirm {published['tag_name']}, update download/coverage text, then replace marker with release-state: available"})
    return {"published": published.get("tag_name") if published else None, "warnings": warnings,
            "read_only": True}


ASSET_NAMES = {"PTBR.zip", "PTBR-COM-PORTRAIT.zip"}


def release_archives(project):
    base = project.archive()
    portraits = project.path("Portrait")
    files = sorted(p for p in portraits.rglob("*") if p.is_file())
    if not files:
        raise Invalid("Missing portrait sources")
    variant = BytesIO()
    with ZipFile(BytesIO(base)) as original, ZipFile(variant, "w", ZIP_DEFLATED) as output:
        for name in original.namelist():
            output.writestr(ZipInfo(name), original.read(name), compress_type=ZIP_DEFLATED)
        for file in files:
            name = file.relative_to(project.root).as_posix()
            output.writestr(ZipInfo(name), project.path(name).read_bytes(), compress_type=ZIP_DEFLATED)
    with ZipFile(variant) as output:
        if output.testzip():
            raise Invalid("Corrupt portrait archive")
    return {"PTBR.zip": base, "PTBR-COM-PORTRAIT.zip": variant.getvalue()}


def publish(project, client, commit):
    receipt = project.verify_output()
    payloads = release_archives(project)
    asset_hashes = {name: sha(content) for name, content in payloads.items()}
    fingerprint = "<!-- ptbr-fingerprint: " + sha(json_bytes(asset_hashes)) + " -->"
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise Invalid("Invalid exact commit SHA")
    if git(project.root, "rev-parse", "HEAD").stdout.decode().strip() != commit:
        raise Invalid("HEAD is not the verified triggering commit")
    if git(project.root, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        raise Invalid("Tracked working tree differs from commit")
    metadata = client.request("GET")  # canonical /repos/owner/repo, no trailing slash
    if metadata.get("full_name", "").lower() != REPOSITORY.lower():
        raise Invalid("Repository identity mismatch")
    branch = metadata["default_branch"]

    def current_head():
        head = client.request("GET", "/commits/"+urllib.parse.quote(branch, safe=""))["sha"]
        if head != commit:
            raise Invalid("STALE_COMMIT: default branch advanced; only its current verified PTBR may publish")

    current_head()
    releases = client.releases()
    stable = [r for r in releases if not r.get("draft") and not r.get("prerelease") and SEMVER.fullmatch(r["tag_name"])]
    legacy_path = project.path(WORK+"legacy-releases.json")
    legacy_receipt = read_json(legacy_path) if legacy_path.exists() else {"tags": {}}
    legacy = legacy_receipt["tags"]
    archived_divergent = set(legacy_receipt.get("archived_divergent_tags", []))
    if not archived_divergent.issubset(legacy):
        raise Invalid("Unknown divergent legacy tag")
    managed = []
    for candidate in stable:
        tag = candidate["tag_name"]
        if tag in legacy:
            if client.tag_sha(tag) != legacy[tag]:
                raise Invalid("LEGACY_TAG_CHANGED: preserved historical tag differs from migration receipt")
            if (tag not in archived_divergent and
                    git(project.root, "merge-base", "--is-ancestor", legacy[tag], commit, allow_failure=True).returncode):
                raise Invalid("NON_ANCESTOR_TAG: legacy release must belong to preserved history")
        else:
            managed.append(candidate)
    stable = managed
    stable.sort(key=lambda r: tuple(map(int, SEMVER.fullmatch(r["tag_name"]).groups())))
    previous = stable[-1] if stable else None
    if previous:
        tag = previous["tag_name"]
        previous_sha = client.tag_sha(tag)
        if not previous_sha or git(project.root, "merge-base", "--is-ancestor", previous_sha, commit, allow_failure=True).returncode:
            raise Invalid("NON_ANCESTOR_TAG: previous stable release must be an ancestor")
        prior = json.loads(git(project.root, "show", f"{previous_sha}:{BUILD}").stdout)
        prior_outputs = prior.get("outputs", {})
        if not prior_outputs or any(not (name.startswith(DEPLOY+"/") or name in {"package.xml", "preview.jpg"}) for name in prior_outputs):
            raise Invalid("Previous release has an unsupported native inventory")
        prior_actual = {name: sha(git(project.root, "show", f"{previous_sha}:PTBR/{name}").stdout)
                        for name in prior_outputs}
        if prior_outputs != prior_actual:
            raise Invalid("Previous release manifest does not match tagged native files")
        if prior_outputs == receipt["outputs"]:
            confirmed = client.request("GET", f"/releases/{previous['id']}")
            assets = confirmed.get("assets", [])
            names = {asset["name"] for asset in assets}
            if names - ASSET_NAMES:
                raise Invalid("Unexpected public release asset set")
            if not confirmed.get("draft") and names == ASSET_NAMES and all(
                a.get("state") == "uploaded" and a.get("digest") == "sha256:" + asset_hashes[a["name"]]
                for a in assets
            ):
                return {"status": "unchanged", "tag": tag, "docs": docs_status(project, confirmed)}
        a, b, c = map(int, SEMVER.fullmatch(tag).groups())
        version = f"v{a}.{b}.{c+1}"
    else:
        versions = [tuple(map(int, SEMVER.fullmatch(t).groups())) for t in legacy if SEMVER.fullmatch(t)]
        if versions:
            a, b, c = max(versions)
            version = f"v{a}.{b}.{c+1}"
        else:
            version = "v1.0.0"
    existing = client.tag_sha(version)
    if existing and existing != commit:
        raise Invalid("TAG_CONFLICT: existing version points to another commit; never retag")
    body = changelog(project, client.tag_sha(previous["tag_name"]) if previous else None, commit, receipt)
    body = body.split("<!-- ptbr-fingerprint:", 1)[0] + fingerprint
    drafts = [r for r in releases if r["tag_name"] == version]
    if len(drafts) > 1:
        raise Invalid("Ambiguous release candidates")
    if drafts:
        release = client.request("GET", f"/releases/{drafts[0]['id']}")
        if not release.get("draft") or release.get("target_commitish") != commit or fingerprint not in release.get("body", ""):
            raise Invalid("Interrupted release does not belong to this build/commit")
    else:
        release = client.request("POST", "/releases", {"tag_name": version, "target_commitish": commit,
                    "name": "Elin — PT-BR "+version, "body": body, "draft": True, "prerelease": False})
    assets = client.request("GET", f"/releases/{release['id']}/assets?per_page=100")
    if any(a.get("name") not in payloads for a in assets):
        raise Invalid("Unexpected draft asset; inspect before publication")
    for name, content in payloads.items():
        matches = [a for a in assets if a["name"] == name]
        if len(matches) > 1:
            raise Invalid(f"Duplicate release assets: {name}")
        if matches:
            asset = matches[0]
            if asset.get("state") != "uploaded" or asset.get("digest") != "sha256:"+sha(content) or asset.get("size") != len(content):
                raise Invalid(f"Interrupted asset differs: {name}; inspect draft rather than silently replace")
        else:
            endpoint = f"/releases/{release['id']}/assets?name="+urllib.parse.quote(name, safe="")
            asset = client.request("POST", endpoint, content, upload=True,
                                   content_type="application/zip" if name.endswith(".zip") else "text/plain; charset=utf-8")
            if asset.get("state") != "uploaded" or asset.get("digest") != "sha256:"+sha(content) or asset.get("size") != len(content):
                raise Invalid(f"Uploaded asset not confirmed: {name}")
    current_head()
    client.request("PATCH", f"/releases/{release['id']}", {"draft": False, "body": body})
    published = client.request("GET", f"/releases/{release['id']}")
    if (set(a.get("name") for a in published.get("assets", [])) != ASSET_NAMES
            or published.get("draft") or published.get("tag_name") != version
            or client.tag_sha(version) != commit
            or any(not any(a.get("name") == name and a.get("state") == "uploaded"
                           and a.get("digest") == "sha256:"+sha(content) and a.get("size") == len(content)
                           for a in published.get("assets", [])) for name, content in payloads.items())):
        raise Invalid("Post-publication asset/tag verification failed; rerun safely")
    return {"status": "published", "tag": version, "docs": docs_status(project, published)}


def main():
    project = Project(Path(__file__).resolve().parent.parent)
    try:
        client = Client(os.environ["GITHUB_TOKEN"], os.environ["GITHUB_REPOSITORY"])
        if len(sys.argv) == 2 and sys.argv[1] == "--docs-status":
            stable = [r for r in client.releases() if not r.get("draft") and not r.get("prerelease") and SEMVER.fullmatch(r["tag_name"])]
            stable.sort(key=lambda r: tuple(map(int, SEMVER.fullmatch(r["tag_name"]).groups())))
            published = client.request("GET", f"/releases/{stable[-1]['id']}") if stable else None
            result = docs_status(project, published)
        else:
            if os.environ.get("GITHUB_EVENT_NAME") not in {"push", "workflow_dispatch"}:
                raise Invalid("Only default-branch push/manual release events are allowed")
            metadata = client.request("GET")
            if os.environ.get("GITHUB_REF") != "refs/heads/"+metadata["default_branch"]:
                raise Invalid("Publishing requires canonical default branch")
            result = publish(project, client, os.environ["GITHUB_SHA"])
        print(json.dumps(result, ensure_ascii=False, indent=2))
        for warning in result.get("docs", result).get("warnings", []):
            print(f"::warning file={warning['file']}::{warning['action']}")
        return 0
    except (Invalid, OSError, KeyError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
