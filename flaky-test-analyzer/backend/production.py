"""Production entry point: ``python -m backend.production``."""

import uvicorn

from backend.config import PORT


def main() -> None:
    uvicorn.run("backend.main:app", host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
