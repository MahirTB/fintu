import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    # Render/Neon Postgres URLs sometimes start with postgres:// but SQLAlchemy requires postgresql://
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        
    # If the URL specifies postgresql+psycopg:// (psycopg 3) but psycopg is not installed, fallback to psycopg2
    if DATABASE_URL.startswith("postgresql+psycopg://"):
        try:
            import psycopg
        except ImportError:
            DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg://", "postgresql+psycopg2://", 1)
    elif DATABASE_URL.startswith("postgresql://"):
        # If psycopg2 is available, postgresql:// defaults to it. If only psycopg (v3) is available, use it.
        try:
            import psycopg2
        except ImportError:
            try:
                import psycopg
                DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
            except ImportError:
                pass

    SQLALCHEMY_DATABASE_URL = DATABASE_URL
    connect_args = {}
else:
    # On serverless platforms (Vercel, AWS Lambda), the filesystem is read-only except /tmp
    if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        db_path = "/tmp/finance.db"
    else:
        db_path = os.path.join(BASE_DIR, "finance.db")
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{db_path}"
    connect_args = {"check_same_thread": False}

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args=connect_args
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
