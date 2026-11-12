#!/usr/bin/env python3
"""Generate the KiCad PCM repository files from packages/<identifier>/.

Each package folder holds a metadata.json (KiCad PCM package schema, all
published versions) and an optional 64x64 icon.png. This script writes
packages.json, resources.zip and repository.json into the repository root.
Timestamps in repository.json only change when the referenced file changes.

--validate checks all files against the KiCad PCM schema (needs jsonschema).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACKAGES_DIR = ROOT / "packages"
BASE_URL = "https://raw.githubusercontent.com/inoson/kicad-packages/main"
SCHEMA_URL = "https://gitlab.com/kicad/code/kicad/-/raw/master/kicad/pcm/schemas/pcm.v1.schema.json"
REPOSITORY = {
    "$schema": "https://go.kicad.org/pcm/schemas/v1#/definitions/Repository",
    "name": "inoson KiCad plugins",
    "maintainer": {
        "name": "inoson",
        "contact": {"github": "https://github.com/inoson/kicad-packages"},
    },
}
ZIP_DATE = (1980, 1, 1, 0, 0, 0)


def to_json_bytes(data: dict) -> bytes:
    return (json.dumps(data, indent=4, ensure_ascii=False) + "\n").encode("utf8")


def load_packages() -> list[dict]:
    packages = []
    for folder in sorted(p for p in PACKAGES_DIR.iterdir() if p.is_dir()):
        metadata = json.loads((folder / "metadata.json").read_text(encoding="utf8"))
        if metadata["identifier"] != folder.name:
            raise SystemExit(
                f"ERROR: {folder.name}/metadata.json has identifier {metadata['identifier']}")
        metadata.pop("$schema", None)
        packages.append(metadata)
    return packages


def build_resources_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for icon in sorted(PACKAGES_DIR.glob("*/icon.png")):
            info = zipfile.ZipInfo(f"{icon.parent.name}/icon.png", ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, icon.read_bytes())
    return buf.getvalue()


def resource_ref(name: str, data: bytes, previous: dict | None, now: int) -> dict:
    sha = hashlib.sha256(data).hexdigest()
    url = f"{BASE_URL}/{name}"
    if previous and previous.get("sha256") == sha and previous.get("url") == url:
        return previous
    return {
        "url": url,
        "sha256": sha,
        "update_timestamp": now,
        "update_time_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now)),
    }


def validate() -> None:
    from jsonschema import Draft7Validator

    with urllib.request.urlopen(SCHEMA_URL) as response:
        schema = json.load(response)

    def check(path: Path, definition: str) -> None:
        validator = Draft7Validator(dict(schema, **{"$ref": f"#/definitions/{definition}"}))
        errors = list(validator.iter_errors(json.loads(path.read_text(encoding="utf8"))))
        for error in errors:
            print(f"{path.relative_to(ROOT)}: {error.json_path}: {error.message}")
        if errors:
            raise SystemExit(1)
        print(f"{path.relative_to(ROOT)}: OK")

    for metadata in sorted(PACKAGES_DIR.glob("*/metadata.json")):
        check(metadata, "Package")
    check(ROOT / "packages.json", "PackageArray")
    check(ROOT / "repository.json", "Repository")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--validate", action="store_true",
                        help="validate against the KiCad PCM schema afterwards")
    args = parser.parse_args()

    packages_raw = to_json_bytes({"packages": load_packages()})
    resources_raw = build_resources_zip()
    (ROOT / "packages.json").write_bytes(packages_raw)
    (ROOT / "resources.zip").write_bytes(resources_raw)

    repository_path = ROOT / "repository.json"
    previous = {}
    if repository_path.exists():
        previous = json.loads(repository_path.read_text(encoding="utf8"))
    now = int(time.time())
    repository = dict(REPOSITORY)
    repository["packages"] = resource_ref(
        "packages.json", packages_raw, previous.get("packages"), now)
    repository["resources"] = resource_ref(
        "resources.zip", resources_raw, previous.get("resources"), now)
    repository_path.write_bytes(to_json_bytes(repository))
    print("Updated packages.json, resources.zip, repository.json")

    if args.validate:
        validate()


if __name__ == "__main__":
    sys.exit(main())
