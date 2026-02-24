from __future__ import annotations

import logging
from pathlib import Path

from .config import AppConfig
from .state_machine import HelloGptStateMachine


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    app = None
    try:
        config = AppConfig.load(project_root)
        _setup_logging(config.log_level)
        app = HelloGptStateMachine(config)
        app.run()
    except KeyboardInterrupt:
        print("\nShutting down...", flush=True)
        if app is not None:
            app.stop()
    except Exception:
        logging.exception("Fatal error")
        raise


if __name__ == "__main__":
    main()
