from pydantic_settings import BaseSettings
from os import getenv
import json

class Settings(BaseSettings):
    # Секретный ключ должен совпадать с тем, что в Auth Service
    JWT_SECRET_KEY: str = getenv("JWT_SECRET_KEY", "your-super-secret-key-change-this-in-production-123!")
    ALGORITHM: str = getenv("ALGORITHM", "HS256")

    # Внутренние URL сервисов (имена контейнеров в Docker-сети)
    SERVICES_URLS: dict[str, str] = json.loads(getenv("SERVICES_URLS", '{"auth": "http://register-auth-service:8001", "problem-service": "http://problem-service:8002", "hypo-service": "http://hypo-service:8003", "grafana": "http://grafana:3000"}'))

    NO_CREDENTIALS_PATHS: list[str] = json.loads(getenv("NO_CREDENTIALS_PATHS", '["/api/auth", "/api/hypo-service", "/api/hypo-service/frontend", "/api/hypothesis", "/api/grafana"]'))

    class Config:
        env_file = ".env"

settings = Settings()
