import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(path=None):
    with open(path or ROOT / "config.toml", "rb") as f:
        return tomllib.load(f)
