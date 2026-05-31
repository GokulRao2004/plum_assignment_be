"""Application factory for Flask application."""
from flask import Flask
from flask_cors import CORS
from app.config import config_by_name
from app.database import init_db
from app.routes.simulate import simulate_bp
from app.routes.claims import claims_bp
from app.logging_config import setup_logging

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
    
    # Setup logging before anything else
    setup_logging(app)
    
    app.logger.info(f'Starting application in {config_name} mode')
    
    # Initialize database, migrations, and JWT
    init_db(app)
    app.logger.info('Database initialized')
    
    # Initialize OCR vocabularies
    try:
        from app.ocr.loaders import warm_vocabs
        from pathlib import Path
        
        base_path = Path(__file__).parent.parent
        vocab_config = {
            'RXNORM_ZIP': str(base_path / 'reference_data' / 'rxnorm.zip'),
            'RXNORM_DIR': str(base_path / 'reference_data' / 'rxnorm_extracted'),
            'DIAGNOSIS_CSV': str(base_path / 'reference_data' / 'diagnosis.csv'),
            'LABTEST_CSV': str(base_path / 'reference_data' / 'labtest.csv')
        }
        
        warm_vocabs(vocab_config)
        app.logger.info('OCR vocabularies initialized')
    except Exception as e:
        app.logger.warning(f'Could not initialize OCR vocabularies: {str(e)}')
        app.logger.warning('OCR will work but medicine/diagnosis matching may be limited')
    
    # Enable CORS with allowed origins from config
    allowed_origins = app.config.get('ALLOWED_ORIGINS', ['http://localhost:3000'])
    CORS(app, 
         origins=allowed_origins, 
         supports_credentials=True,
         allow_headers=['Content-Type', 'Authorization'],
         expose_headers=['Content-Type'],
         methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])
    app.logger.info(f'CORS enabled for origins: {allowed_origins}')
    
    # Register blueprints with URL prefixes
    app.register_blueprint(simulate_bp)
    app.register_blueprint(claims_bp)
    app.logger.info('Blueprints registered')
    
    # Add error handlers to ensure CORS headers on error responses
    @app.errorhandler(400)
    def bad_request(error):
        response = {
            'error': 'bad_request',
            'message': str(error) if str(error) != '400 Bad Request: The browser (or proxy) sent a request that this server could not understand.' else 'Bad request'
        }
        from flask import jsonify
        return jsonify(response), 400
    
    @app.errorhandler(500)
    def internal_error(error):
        app.logger.error(f'Internal server error: {str(error)}')
        response = {
            'error': 'internal_server_error',
            'message': 'An internal server error occurred. Please try again later.'
        }
        from flask import jsonify
        return jsonify(response), 500
    
    return app
