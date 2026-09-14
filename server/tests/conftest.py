import sys
from pathlib import Path

# make `main` importable whether pytest runs from repo root or from api/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
