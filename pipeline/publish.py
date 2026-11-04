"""Copy the unit catalog (build/catalog.npz, from units.py) to the app.

  SIP_PUBLISH=<user@host:directory> python publish.py

The app reads the catalog from its state directory and picks up a new one with its next
request (server/catalog.py), so publishing needs no restart. rsync writes the file
under a temporary name and renames it when complete, so the app never reads half of it.
"""

import os
import subprocess

from config import CATALOG


def main():
    target = os.environ.get("SIP_PUBLISH")
    if not target:
        raise SystemExit("SIP_PUBLISH not set: user@host:directory of the app's state")
    subprocess.run(["rsync", "--chmod=F644", "--checksum", str(CATALOG), target.rstrip("/") + "/catalog.npz"],
                   check=True)
    print(f"published {CATALOG.stat().st_size / 1e6:.1f} MB to {target}")


if __name__ == "__main__":
    main()
