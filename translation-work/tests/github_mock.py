import copy
import json
import urllib.parse

import release
from storage import sha

class GitHubMock:
    """Exercises Client.request URL/headers/body and publication side effects."""
    def __init__(self, head):
        self.head = head
        self.releases = []
        self.tags = {}
        self.calls = []
        self.fail_upload = False
        self.fail_upload_name = None
        self.statuses = []

    def transport(self, method, url, headers, raw):
        parsed = urllib.parse.urlparse(url)
        base = "/repos/"+release.REPOSITORY
        path = parsed.path
        self.calls.append((method, parsed.netloc, path, parsed.query))
        assert headers["Authorization"] == "Bearer test-token"
        assert path.startswith(base)
        endpoint = path[len(base):]
        assert not endpoint.endswith("/")
        if self.statuses:
            status = self.statuses.pop(0)
            if status != 200:
                return status, b'{}', {}
        data = json.loads(raw) if raw and "json" in headers.get("Content-Type", "") else None
        status, result = 200, None
        if endpoint == "":
            result = {"full_name": release.REPOSITORY, "default_branch": "main"}
        elif endpoint == "/commits/main":
            result = {"sha": self.head}
        elif endpoint == "/releases" and method == "GET":
            result = copy.deepcopy(self.releases)
        elif endpoint.startswith("/git/ref/tags/"):
            tag = urllib.parse.unquote(endpoint.split("/tags/", 1)[1])
            if tag in self.tags:
                result = {"object": {"type": "commit", "sha": self.tags[tag]}}
            else:
                status, result = 404, {"message": "Not Found"}
        elif endpoint == "/releases" and method == "POST":
            result = {**data, "id": len(self.releases)+1, "assets": []}
            self.releases.append(result)
        elif endpoint.startswith("/releases/"):
            parts = endpoint.split("/")
            rid = int(parts[2])
            r = next(r for r in self.releases if r["id"] == rid)
            if len(parts) == 4 and parts[3] == "assets":
                if method == "GET":
                    result = r["assets"]
                else:
                    assert parsed.netloc == "uploads.github.com"
                    asset_name = urllib.parse.parse_qs(parsed.query)["name"][0]
                    assert asset_name in release.ASSET_NAMES
                    if self.fail_upload or self.fail_upload_name == asset_name:
                        return 403, b'{}', {}
                    result = {"name": asset_name, "id": 100+rid+len(r["assets"]), "state": "uploaded",
                              "digest": "sha256:"+sha(raw), "size": len(raw)}
                    r["assets"].append(result)
            elif method == "PATCH":
                r.update(data)
                if not r["draft"]:
                    self.tags[r["tag_name"]] = r["target_commitish"]
                result = r
            else:
                result = r
        else:
            raise AssertionError((method, url))
        return status, json.dumps(result).encode(), {}


