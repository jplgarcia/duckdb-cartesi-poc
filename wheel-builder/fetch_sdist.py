"""Download the DuckDB sdist from PyPI and verify its sha256.

usage: fetch_sdist.py <version> <expected_sha256 or ""> <dest>
If no sha256 is given, the one PyPI publishes for the file is used.
"""
import hashlib
import json
import sys
import urllib.request

version, expected, dest = sys.argv[1], sys.argv[2], sys.argv[3]
meta = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/duckdb/{version}/json"))
sdist = next(u for u in meta["urls"] if u["packagetype"] == "sdist")
expected = expected or sdist["digests"]["sha256"]

data = urllib.request.urlopen(sdist["url"]).read()
actual = hashlib.sha256(data).hexdigest()
print(f"{sdist['filename']} sha256={actual}")
if actual != expected:
    sys.exit(f"sha256 mismatch: expected {expected}")
with open(dest, "wb") as f:
    f.write(data)
