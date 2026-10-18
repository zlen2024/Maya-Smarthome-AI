"""The library has one version, written in three places. Fail if they disagree.

    python extras/test/check_version.py

library.properties (what the Arduino IDE shows), the MAYA_LIB_VERSION macro in
src/Maya.h (what the Serial banner and the Bluetooth INFO characteristic report), and
the newest heading in CHANGELOG.md. Bumping one without the others is how a board ends
up reporting a version its own library does not have.
"""
import pathlib
import re
import sys

root = pathlib.Path(__file__).resolve().parents[2]
props = re.search(r"^version=(\S+)", (root / "library.properties").read_text(encoding="utf-8"), re.M)
header = re.search(r'#define\s+MAYA_LIB_VERSION\s+"([^"]+)"', (root / "src" / "Maya.h").read_text(encoding="utf-8"))
log = re.search(r"^##\s*\[?(\d+\.\d+\.\d+)", (root / "CHANGELOG.md").read_text(encoding="utf-8"), re.M)

found = {"library.properties": props and props.group(1),
         "src/Maya.h": header and header.group(1),
         "CHANGELOG.md": log and log.group(1)}
for where, v in found.items():
    print(f"  {where:22} {v}")
if None in found.values() or len(set(found.values())) != 1:
    print("FAIL: the versions differ or one is missing")
    sys.exit(1)
print("ok: one version everywhere")
