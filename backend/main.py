"""Backend process entry point."""

import os

import uvicorn

from backend.api.app import create_app


app = create_app()


def run() -> None:
    uvicorn.run(
        app,
        host=os.getenv("API_HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", os.getenv("API_PORT", "8000"))),
        reload=False,
    )


if __name__ == "__main__":
    run()
