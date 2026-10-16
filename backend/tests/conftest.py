"""PyTest configuration and global fixtures.

Loads project .env at startup so pytest runs can use real model credentials when needed,
while all standard tests run in dry-run mode without requiring any API key.
"""

from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")
load_dotenv()
