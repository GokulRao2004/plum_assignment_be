"""Application factory for Flask application."""
from flask import Flask
from flask_cors import CORS
from app.config import config_by_name
from app.database import init_db


def create_app(config_name='development'):
    """Create and configure the Flask application.
    
    Uses the application factory pattern with lazy initialization of database,
    migrations, and JWT authentication.
    
    Args:
        config_name: Configuration environment (development, testing, production)
    
    Returns:
        Flask application instance with all extensions initialized
    """
    app = Flask(__name__)
    app.config.from_object(config_by_name[config_name])
    
    # Initialize database, migrations, and JWT
    init_db(app)
    
    # Enable CORS with allowed origins from config
    allowed_origins = app.config.get('ALLOWED_ORIGINS', ['http://localhost:3000'])
    CORS(app, origins=allowed_origins, supports_credentials=True)
    
    # Register blueprints with URL prefixes
    
    
    return app
