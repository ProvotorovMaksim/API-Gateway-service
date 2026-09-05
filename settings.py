from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Секретный ключ должен совпадать с тем, что в Auth Service
    JWT_SECRET_KEY: str = "your-super-secret-key-change-this-in-production-123!"
    ALGORITHM: str = "HS256"

    # Внутренние URL сервисов (имена контейнеров в Docker-сети)
    SERVICES_URLS: dict[str, str] = {
        "auth": "http://register-auth-service:8001",
        "problem-service": "http://problem-service:8002",
    }

    NO_CREDENTIALS_PATHS: list[str] = [
        "/api/auth",
        "/api/auth/login",
        "/api/auth/register",
        "/api/hypo-service",
        "/api/hypo-service/frontend",
        "/api/hypothesis"
    ]

    class Config:
        env_file = ".env"

settings = Settings()
