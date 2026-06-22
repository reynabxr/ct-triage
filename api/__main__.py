from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

def main() -> None:
    load_dotenv()
    host = os.getenv("PYTHON_API_HOST", "127.0.0.1")
    port = os.getenv("PYTHON_API_PORT", "8000")

    try:
        import uvicorn  # type: ignore

        uvicorn.run("api.app:app", host=host, port=int(port), reload=False)
        return
    except ModuleNotFoundError:
        repo_root = Path(__file__).resolve().parent.parent
        venv_python = repo_root / ".venv" / "bin" / "python"
        if venv_python.exists() and venv_python != Path(sys.executable):
            os.execv(
                str(venv_python),
                [str(venv_python), "-m", "uvicorn", "api.app:app", "--host", host, "--port", port],
            )
        raise


if __name__ == "__main__":
    main()
