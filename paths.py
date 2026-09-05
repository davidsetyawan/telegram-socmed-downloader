from pathlib import Path

DATA_DIR = Path(__file__).parent / "storage"
TMP_DIR = Path(__file__).parent / "tmp"
DATA_DIR.mkdir(parents=True, exist_ok=True)
TMP_DIR.mkdir(parents=True, exist_ok=True)
