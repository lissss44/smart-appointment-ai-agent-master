"""Start the local app with the project environment and Windows certificates."""

from pathlib import Path
import argparse
import os

import truststore

truststore.inject_into_ssl()

from dotenv import load_dotenv
import uvicorn


def main():
    parser = argparse.ArgumentParser(description="Start Smart Appointment AI Agent locally")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    os.chdir(root)
    load_dotenv(root / ".env")
    required = (
        "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL",
        "EMBEDDING_API_KEY", "EMBEDDING_BASE_URL", "EMBEDDING_MODEL",
    )
    missing = [name for name in required if not os.getenv(name)
               or os.environ[name].startswith("your_")]
    if missing:
        raise SystemExit("Missing configuration: " + ", ".join(missing)
                         + ". Check .env and DASHSCOPE_API_KEY in Windows environment variables.")

    (root / "data").mkdir(exist_ok=True)
    print(f"Open http://127.0.0.1:{args.port} (Ctrl+C to stop)", flush=True)
    uvicorn.run("app:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
