#!/usr/bin/env python3
"""Download the sample Sensor Logger recording into ingestion/inbox/<venue>/.

The timing-sheet JSON files that go with it are already in git. After this runs,
the inbox is complete and Stage A can be run:

    python fetch_sample_data.py
    .venv/bin/python ingestion/kart/run.py
    .venv/bin/python ingestion/kart/run_stage_b.py
    .venv/bin/python ingestion/kart/show_coaching.py
"""
import sys
import urllib.request
from pathlib import Path

RELEASE = "https://github.com/nathanverrill/racecraft/releases/download/sample-data-v1"
FILES = {
    "gateway-kartplex": ["World_Wide_Technology_Raceway-2026-06-25_21-02-36.zip"],
}

HERE = Path(__file__).resolve().parent
INBOX = HERE / "ingestion" / "inbox"


def download(url: str, dest: Path) -> None:
    def hook(blocks, block_size, total):
        done = blocks * block_size
        if total > 0:
            pct = min(100, done * 100 // total)
            sys.stdout.write(f"\r  {dest.name}: {pct}% of {total / 1e6:.0f} MB")
        else:
            sys.stdout.write(f"\r  {dest.name}: {done / 1e6:.0f} MB")
        sys.stdout.flush()

    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp, hook)
    tmp.rename(dest)
    print()


def main() -> None:
    for venue, names in FILES.items():
        vdir = INBOX / venue
        vdir.mkdir(parents=True, exist_ok=True)
        for name in names:
            dest = vdir / name
            if dest.exists():
                print(f"  {name}: already present, skipping")
                continue
            download(f"{RELEASE}/{name}", dest)
    print(f"\nInbox ready: {INBOX}")
    print("Next: .venv/bin/python ingestion/kart/run.py")


if __name__ == "__main__":
    main()
