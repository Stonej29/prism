"""Run the PRISM web server: `python -m prism.web` or `prism-web`."""
from __future__ import annotations

from prism.config import load_web_settings


def main() -> None:
    import uvicorn

    settings = load_web_settings()
    uvicorn.run(
        "prism.web.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
    )


if __name__ == "__main__":
    main()
