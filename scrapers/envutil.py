import os
from dotenv import load_dotenv

load_dotenv()

def require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

def optional(name: str, default: str = "") -> str:
    return os.getenv(name, default)
