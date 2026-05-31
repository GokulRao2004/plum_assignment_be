"""Celery worker startup script."""
import os
from app.celery_app import celery
from app import create_app

# Set Flask environment
os.environ.setdefault('FLASK_ENV', 'development')

# Create Flask app to initialize database and other extensions
app = create_app()

if __name__ == '__main__':
    # Start the Celery worker
    celery.start()
