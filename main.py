from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import Response, FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError, ExpiredSignatureError
import httpx
from settings import settings
from logging import getLogger

logger = getLogger("main")
logger.setLevel("INFO")

security = HTTPBearer(auto_error=False)
app = FastAPI(title="API Gateway")

http_client = httpx.AsyncClient()

@app.on_event("shutdown")
async def shutdown_event():
    await http_client.aclose()

@app.get("/", include_in_schema=False)
async def serve_frontend():
    return FileResponse("index.html")

# --- Гибкая проверка токена ---
async def verify_token_optional(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Проверяет токен, но только если путь не начинается с auth/"""
    path = request.url.path
    logger.info(f"Проверка токена для пути: {path}")
    
    # Для auth-эндпоинтов токен не требуется
    if any(path.startswith(ncp) for ncp in settings.NO_CREDENTIALS_PATHS):
        return None
    
    if not credentials:
        raise HTTPException(status_code=401, detail="Отсутствует заголовок авторизации")
    
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Некорректный токен: отсутствует 'sub'")
        return str(user_id)
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Срок действия токена истек")
    except JWTError as e:
        logger.error(f"Ошибка валидации JWT: {str(e)}")
        raise HTTPException(status_code=401, detail=f"Недействительный токен: {str(e)}")

# --- Единый прокси-маршрут ---
@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_to_service(request: Request, path: str, user_id: str = Depends(verify_token_optional)):
    service_name = path.split("/")[0]
    
    if service_name not in settings.SERVICES_URLS:
        raise HTTPException(status_code=404, detail=f"Сервис '{service_name}' не найден")
    
    remaining_path = path[len(service_name):].lstrip("/")
    base_url = settings.SERVICES_URLS[service_name]
    target_url = f"{base_url}/{remaining_path}" if remaining_path else base_url

    headers = dict(request.headers)
    if user_id:  # Добавляем X-User-Id только если токен был валиден
        headers["X-User-Id"] = user_id
    headers.pop("host", None)
    headers.pop("content-length", None)
    
    try:
        response = await http_client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            params=request.query_params,
            content=await request.body()
        )
        
        return Response(
            content=response.content,
            status_code=response.status_code,
            media_type=response.headers.get("content-type", "application/json"),
            headers={k: v for k, v in response.headers.items() if k.lower() not in ["content-length", "transfer-encoding"]}
        )
    except httpx.RequestError as exc:
        logger.error(f"Ошибка проксирования к {target_url}: {exc}")
        raise HTTPException(status_code=502, detail=f"Не удалось связаться с сервисом '{service_name}'")

@app.get("/health", include_in_schema=False)
async def health_check():
    return {"status": "ok"}
