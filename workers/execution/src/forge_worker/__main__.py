"""Module entrypoint for `python -m forge_worker`."""

from forge_worker.main import run

if __name__ == "__main__":
    import sys

    sys.exit(run())
