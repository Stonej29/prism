"""Run the PRISM web server: `python -m prism.web` or `prism-web`."""
from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    host = os.getenv("PRISM_WEB_HOST", "127.0.0.1")
    port = int(os.getenv("PRISM_WEB_PORT", "8000"))
    reload = os.getenv("PRISM_WEB_RELOAD", "").lower() in {"1", "true", "yes"}
    uvicorn.run("prism.web.app:create_app", factory=True, host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
