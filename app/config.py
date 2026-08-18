import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "LinkPlease Instagram DM Automation"
    DEBUG: bool = False
    
    # Mock Instagram API Configuration
    MOCK_API_BASE_URL: str = "https://pseudogram-api.onrender.com"
    API_KEY: str = ""
    
    # Signature verification (Part B)
    VERIFY_SIGNATURE: bool = True
    
    # Database
    DATABASE_PATH: str = "data/linkplease.db"
    
    # Rate Limiting & Queue Strategy (Part C)
    # Mock API limit: 10 requests per rolling 60 seconds
    RATE_LIMIT_MAX_REQUESTS: int = 10
    RATE_LIMIT_WINDOW_SECONDS: float = 60.0
    
    # Worker & Retry Settings
    MAX_SEND_ATTEMPTS: int = 5
    INITIAL_BACKOFF_SECONDS: float = 2.0
    WORKER_POLL_INTERVAL_SECONDS: float = 0.2
    
    # Reconciler Settings (Part C)
    RECONCILER_POLL_INTERVAL_SECONDS: float = 2.0
    MAX_RECONCILE_RETRIES: int = 3
    
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore"
    }

settings = Settings()
