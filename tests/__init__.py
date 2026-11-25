import sys
from pathlib import Path

# Let the tests run without installing the package: python -m unittest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
