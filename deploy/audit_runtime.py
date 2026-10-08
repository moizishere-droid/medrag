"""Audit exact installed serving packages; run with an isolated pip-audit tool."""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

# These three trusted, pinned model wheels are not published on PyPI.
MODEL_WHEELS = {"en-core-sci-md", "en-ner-bc5cdr-md", "en-core-web-sm"}


def audit(packages_path, output):
    packages = json.loads(Path(packages_path).read_text(encoding="utf-8"))
    pins = []
    for package in packages:
        name = package["name"].lower().replace("_", "-")
        if name not in MODEL_WHEELS:
            pins.append(f"{name}=={package['version'].split('+')[0]}")
    with tempfile.TemporaryDirectory(prefix="medrag-audit-") as directory:
        requirements = Path(directory) / "installed.txt"
        requirements.write_text("\n".join(pins) + "\n", encoding="utf-8")
        return subprocess.run([sys.executable, "-m", "pip_audit", "--disable-pip", "--no-deps",
                               "-r", str(requirements), "-f", "json", "-o", str(output)], check=False).returncode


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("packages")
    parser.add_argument("output")
    args = parser.parse_args()
    raise SystemExit(audit(args.packages, args.output))
