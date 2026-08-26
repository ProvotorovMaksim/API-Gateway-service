from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Секретный ключ должен совпадать с тем, что в Auth Service
    JWT_SECRET_KEY: str = "your-super-secret-key-change-this-in-production-123!"
    ALGORITHM: str = "HS256"

    # Внутренние URL сервисов (имена контейнеров в Docker-сети)
    AUTH_SERVICE_URL: str = "http://auth-service:8000"
    BILLING_SERVICE_URL: str = "http://billing-service:8008"
    NOTIFICATION_SERVICE_URL: str = "http://notification-service:8009"

    class Config:
        env_file = ".env"

settings = Settings()
