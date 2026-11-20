from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.yml"

with CONFIG_PATH.open() as f:
    CONFIG = yaml.safe_load(f)
