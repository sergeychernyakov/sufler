# main.py

"""
Main entry point for the application.

This module serves as the primary entry point for running the application.
It initializes the necessary components and starts the main program flow.
"""

import sys
from typing import NoReturn

from src.helpers.logger import get_logger

logger = get_logger(__name__)


def main() -> NoReturn:
    """
    Main function that runs the application.

    This function initializes the application, sets up logging,
    and runs the main program logic.

    Returns:
        NoReturn: This function runs indefinitely or exits via sys.exit()
    """
    logger.info("Starting application")

    try:
        # Main application logic would go here
        logger.info("Application initialized successfully")

        # Example: Run your main application logic
        # from src.services import your_service
        # your_service.run()

        logger.info("Application running...")

    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
        sys.exit(0)
    except RuntimeError as e:
        logger.error("Application error: %s", str(e), exc_info=True)
        sys.exit(1)
    finally:
        logger.info("Application shutting down")


if __name__ == "__main__":
    main()
