"""Logging configuration for the application."""
import logging
import sys
from logging.handlers import RotatingFileHandler
import os


def setup_logging(app):
    """Configure application logging.
    
    Sets up:
    - Application logger with INFO level
    - Console and file handlers
    - Disables SQLAlchemy SQL query logs
    - Disables werkzeug logs (Flask development server)
    
    Args:
        app: Flask application instance
    """
    # Create logs directory if it doesn't exist
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    # Configure root logger level
    logging.basicConfig(level=logging.WARNING)
    
    # Disable SQLAlchemy engine logs (SQL queries)
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.dialects').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.orm').setLevel(logging.WARNING)
    
    # Disable werkzeug logs (Flask development server)
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    
    # Configure application logger
    app.logger.setLevel(logging.INFO)
    
    # Remove existing handlers to avoid duplicates
    app.logger.handlers.clear()
    
    # Create formatter
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler - outputs to stdout
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    app.logger.addHandler(console_handler)
    
    # File handler - rotating file handler (10MB max, keep 5 backups)
    log_file = os.path.join(log_dir, 'app.log')
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    app.logger.addHandler(file_handler)
    
    # Prevent propagation to root logger
    app.logger.propagate = False
    
    app.logger.info('Application logging configured successfully')
    app.logger.info(f'Log file location: {log_file}')


def get_logger(name):
    """Get a logger instance for a specific module.
    
    Args:
        name: Name of the logger (typically __name__)
    
    Returns:
        Logger instance configured with application settings
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Ensure SQLAlchemy logs are disabled for this logger too
    if 'sqlalchemy' in name:
        logger.setLevel(logging.WARNING)
    
    return logger
