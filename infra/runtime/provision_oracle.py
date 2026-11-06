"""One-time privileged volume provisioning; never used by application services."""

import os
import shutil
from pathlib import Path

source = Path("/source")
target = Path("/target")
if any(target.iterdir()):
    raise SystemExit("Private volume must be empty; existing snapshots are never overwritten")
for name in ("source_manifest.json", "oracle"):
    path = source / name
    if path.is_dir():
        shutil.copytree(path, target / name)
    else:
        shutil.copyfile(path, target / name)
for path in [target, *target.rglob("*")]:
    os.chown(path, 10002, 10002)
    path.chmod(0o700 if path.is_dir() else 0o600)
