"""Opt-in real Auth/PostgREST smoke. Loopback only, no secrets in output."""

import json
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4


def main():
    if sys.argv[1:] != ["--local"]:
        raise SystemExit("Use --local explicitly; no remote target is supported.")
    root = Path(__file__).resolve().parents[1]
    status = subprocess.run(
        ["supabase", "status", "--output", "json"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if status.returncode:
        raise SystemExit("Local Supabase unavailable")
    config = json.loads(status.stdout)
    url = config["API_URL"]
    parsed = urlparse(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.port != 54321
    ):
        raise SystemExit("Rejected non-local target")
    key = config["ANON_KEY"]

    def request(path, data=None, token=None, method=None):
        headers = {"apikey": key, "Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = Request(
            url + path,
            data=None if data is None else json.dumps(data).encode(),
            headers=headers,
            method=method,
        )
        try:
            with urlopen(req, timeout=20) as response:
                return response.status, json.loads(response.read() or b"null")
        except HTTPError as error:
            return error.code, None

    def user():
        credentials = {
            "email": f"shopping-{uuid4()}@example.test",
            "password": secrets.token_urlsafe(32),
        }
        code, result = request("/auth/v1/signup", credentials)
        assert code == 200, "synthetic signup failed"
        return result["access_token"]

    a, b = user(), user()
    item = str(uuid4())
    operation = {
        "p_operation_id": str(uuid4()),
        "p_kind": "add",
        "p_payload": {
            "id": item,
            "name": "arroz",
            "raw_text": "500 g arroz",
            "quantity": 500,
            "unit": "g",
        },
    }
    rpc = "/rest/v1/rpc/shopping_mutation_v1"
    code, first = request(rpc, operation, a)
    assert code == 200, "add failed"
    code, replay = request(rpc, operation, a)
    assert code == 200 and replay == first, "retry changed result"
    second = {
        "p_operation_id": str(uuid4()),
        "p_kind": "add",
        "p_payload": {
            "id": str(uuid4()),
            "name": "arroz",
            "raw_text": "0,5 kg arroz",
            "quantity": 0.5,
            "unit": "kg",
        },
    }
    code, merged = request(rpc, second, a)
    assert code == 200 and merged["id"] == item and merged["quantity"] == 1000, (
        "mass merge failed"
    )
    code, invisible = request("/rest/v1/shopping_items?select=id", token=b)
    assert code == 200 and invisible == [], "B can read A items"
    code, invisible = request("/rest/v1/shopping_lists?select=id", token=b)
    assert code == 200 and invisible == [], "B can read A list"
    edit = {
        "p_operation_id": str(uuid4()),
        "p_kind": "edit",
        "p_payload": {"id": item, "name": "stolen", "revision": 2},
    }
    code, _ = request(rpc, edit, b)
    assert code >= 400, "B could edit A"
    code, _ = request(
        f"/rest/v1/shopping_items?id=eq.{item}", {"revision": 999}, a, "PATCH"
    )
    assert code == 403, "direct audit write allowed"
    delete = {
        "p_operation_id": str(uuid4()),
        "p_kind": "delete",
        "p_payload": {"id": item, "revision": 2},
    }
    code, deleted = request(rpc, delete, a)
    assert code == 200 and deleted["deleted_at"], "delete failed"
    request(rpc, operation, a)
    code, snapshot = request("/rest/v1/rpc/shopping_snapshot_v1", {}, a)
    assert code == 200 and snapshot["items"][0]["deleted_at"], "replay resurrected item"
    print(
        "PASS: local Auth/PostgREST shopping; replay, kg/g, A/B, audit protection, tombstone (9 checks)."
    )


if __name__ == "__main__":
    main()
