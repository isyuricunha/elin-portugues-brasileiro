"""Read-only affirmative consent guard; never manufactures consent."""
import json
import os
from pathlib import Path
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from native import Invalid
from storage import safe

ATTESTATION = ("Li CONTRIBUTING.md e GAME-DEVELOPER-PERMISSION.md. Autorizo o uso e a adaptação "
               "das minhas contribuições originais deste PR sob CC BY-NC-SA 4.0 e a concessão da "
               "permissão adicional de integração oficial comercial à desenvolvedora/editora do jogo, "
               "com créditos, sem pagamentos ou novas aprovações individuais. Declaro ter os direitos necessários.")


def check(root, event):
    pr = event["pull_request"]
    body = pr.get("body") or ""
    if not any(line.strip() in {"- [x] "+ATTESTATION, "- [X] "+ATTESTATION} for line in body.splitlines()):
        raise Invalid("CONSENT_MISSING: contributor must personally affirm the PR declaration")
    path = safe(root, f"translation-work/contributor-consents/PR-{event['number']}.json")
    record = json.loads(path.read_text(encoding="utf-8"))
    expected = {"identity": pr["user"]["login"], "pull_request": pr["html_url"],
                "scope": "original contributions in this pull request",
                "permission": "CC-BY-NC-SA-4.0 + official-game-commercial-integration", "affirmative": True}
    if record != expected or record["affirmative"] is not True:
        raise Invalid("CONSENT_SCOPE: record does not match this PR/contributor")
    return {"consent": "recorded", "identity": record["identity"], "pull_request": record["pull_request"]}


if __name__ == "__main__":
    try:
        print(json.dumps(check(Path.cwd(), json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))), ensure_ascii=False))
    except (Invalid, OSError, KeyError, ValueError) as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(2)
