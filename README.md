# Insurance Claims Processing Backend

A Flask-based backend system for automated insurance claims processing with OCR capabilities, policy validation, and asynchronous task processing.

## Prerequisites

- **Python**: 3.9+
- **PostgreSQL**: 14+
- **Redis**: 6+
- **Tesseract OCR**: 4.0+
- **Poppler**: (for PDF processing)
- **RXNCONSO.RRF** : Download the dataset from google and add the file to ./reference_data/rxnorm_extracted/ 


## Quick Start

### 1. Clone and Setup Environment

```bash
cd Backend
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your configuration:
```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/test
CELERY_BROKER_URL=redis://localhost:6379/0
SECRET_KEY=your-secret-key-here
JWT_SECRET_KEY=your-jwt-secret-key-here
```

### 3. Start Services

**Terminal 1 - PostgreSQL:**
```bash
# Ensure PostgreSQL is running
# Windows: Check Services
# macOS/Linux:
brew services start postgresql  # macOS
sudo systemctl start postgresql # Linux
```

**Terminal 2 - Redis:**
```bash
# Windows:
redis-server
# macOS:
brew services start redis
# Linux:
sudo systemctl start redis
```

### 4. Initialize Database

```bash
# Create database
createdb insurance_db

# Run migrations
flask db upgrade
```

### 5. Run Application

**Terminal 3 - Flask Server:**
```bash
python wsgi.py
# Server runs on http://localhost:5000
```

**Terminal 4 - Celery Worker:**
```bash
celery -A celery_worker.celery worker --loglevel=info
```

### 6. Generate Test Images
Use "gen docs.ipynb" to generate the images required for using and testing OCR modules.
It generates a set of random images for testing purposes.  


## API Endpoints

### Claims Management
- `POST /api/claims` - Create new claim
- `GET /api/claims` - List all claims
- `GET /api/claims/{id}` - Get claim details
- `PATCH /api/claims/{id}` - Update claim status

### Document Processing
- `POST /api/claims/{id}/documents` - Upload document
- `GET /api/claims/{id}/documents` - List claim documents

### Simulation
- `POST /api/simulate/claim` - Simulate claim processing

## Project Structure

```
Backend/
├── app/
│   ├── agents/          # AI agents for validation
│   ├── models/          # SQLAlchemy models
│   ├── ocr/             # OCR pipeline
│   ├── routes/          # API endpoints
│   ├── tasks/           # Celery tasks
│   └── utils/           # Helper functions
├── migrations/          # Alembic migrations
├── logs/               # Application logs
├── wsgi.py             # Application entry point
└── celery_worker.py    # Celery worker entry point
```

## Development

### Running Tests

```bash
# Install test dependencies
pip install pytest pytest-cov

# Run tests with coverage
pytest --cov=app --cov-report=html

# View coverage report
open htmlcov/index.html
```

### Database Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback migration
alembic downgrade -1
```



## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `FLASK_ENV` | Environment mode | `development` |
| `DATABASE_URL` | PostgreSQL connection string | Required |
| `CELERY_BROKER_URL` | Redis URL for Celery | `redis://localhost:6379/0` |
| `SECRET_KEY` | Flask secret key | Required in production |
| `JWT_SECRET_KEY` | JWT signing key | Required in production |
| `ALLOWED_ORIGINS` | CORS allowed origins | `http://localhost:3000` |

### Policy Configuration

Edit `app/utils/policy_terms.json` to configure insurance policy rules and validation criteria.

## Troubleshooting

**Database Connection Error:**
```bash
# Verify PostgreSQL is running
psql -U postgres -c "SELECT version();"
```

**Redis Connection Error:**
```bash
# Test Redis connection
redis-cli ping
# Should return: PONG
```

**Tesseract Not Found:**
```bash
# Verify installation
tesseract --version

# Windows: Add to PATH
# C:\Program Files\Tesseract-OCR
```

**Celery Tasks Not Processing:**
```bash
# Check Redis connection
redis-cli ping

# Restart Celery worker
celery -A celery_worker.celery worker --loglevel=debug
```

## Production Deployment

### Environment Setup

```bash
export FLASK_ENV=production
export DATABASE_URL=postgresql://user:pass@host:5432/dbname
export SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')
export JWT_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')
```