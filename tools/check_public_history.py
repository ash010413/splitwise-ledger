"""Audit reachable Git history without printing credentials or matched contents."""

import argparse
import re
import subprocess
from pathlib import Path

from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--sensitive-text-file")
    args = parser.parse_args()
    repo = str(Path(args.repo).resolve())
    values = dotenv_values(args.env) if Path(args.env).exists() else {}
    names = [
        "APP_API_TOKEN",
        "TOKEN_ENCRYPTION_KEY",
        "GEMINI_API_KEY",
        "SPLITWISE_CLIENT_SECRET",
        "SPLITWISE_CLIENT_ID",
        "GOOGLE_SHEET_ID",
    ]
    needles = [str(values[name]).encode() for name in names if values.get(name)]
    if args.sensitive_text_file:
        needles.extend(
            line.encode()
            for line in Path(args.sensitive_text_file).read_text().splitlines()
            if line
        )
    output = subprocess.check_output(
        ["git", "-C", repo, "rev-list", "--objects", "--all"], text=True
    )
    objects = dict(
        line.split(" ", 1) if " " in line else (line, "") for line in output.splitlines()
    )
    process = subprocess.Popen(
        ["git", "-C", repo, "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE
    )
    findings = []
    count = 0
    assert process.stdin is not None and process.stdout is not None
    for oid, path in objects.items():
        process.stdin.write((oid + "\n").encode())
        process.stdin.flush()
        header = process.stdout.readline().split()
        data = process.stdout.read(int(header[2]))
        process.stdout.read(1)
        if header[1] != b"blob":
            continue
        count += 1
        if any(value in data for value in needles):
            findings.append((path, "local credential or private data match"))
        if re.search(
            rb"AIza[0-9A-Za-z_-]{35}|ghp_[0-9A-Za-z]{36}|sk-proj-[0-9A-Za-z_-]{32,}", data
        ):
            findings.append((path, "credential pattern"))
        if re.search(r"(^|/)(\.env|Development\.local\.xcconfig)$|\.(sqlite3?|pem|key)$", path):
            findings.append((path, "private file in history"))
    process.stdin.close()
    process.wait()
    print(f"Audited {count} reachable file versions; {len(findings)} findings.")
    for path, kind in sorted(set(findings)):
        print(f"{path}: {kind}")
    raise SystemExit(1 if findings else 0)


if __name__ == "__main__":
    main()
