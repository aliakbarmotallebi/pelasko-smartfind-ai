from __future__ import annotations

import logging
import sys

from app.indexing.builder import build_index

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    try:
        total = build_index()
        logger.info("Index build completed successfully (%d products)", total)
    except Exception as exc:
        logger.exception("Index build failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
