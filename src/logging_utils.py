# src/logging_utils.py

import logging
from logging.handlers import RotatingFileHandler
from src import config

def setup_logging():
    """
    Sets up a rotating file logger.
    This should be called once at the start of the application.
    """
    if not config.LOG_FILE_PATH:
        logging.warning("LOG_FILE_PATH not set in .env, skipping file logging setup.")
        return

    # Get the root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO) # Set the minimum level for the root logger

    # Create a rotating file handler
    # This will create up to 5 backup files of 5MB each.
    file_handler = RotatingFileHandler(
        config.LOG_FILE_PATH,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5,
        encoding='utf-8'
    )

    # Create a formatter and set it for the handler
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)

    # Add the handler to the root logger
    logger.addHandler(file_handler)

    logging.info("File logger setup complete.")
