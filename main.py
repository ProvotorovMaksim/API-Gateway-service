from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import Response  # <-- Добавлено для безопасного проксирования
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

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Отсутствует заголовок авторизации")
    
    token = credentials.credentials
    
    # ОТЛАДКА: Выводим ровно ту строку, которую пытается расшифровать jose
    logger.info(f"DEBUG: Попытка декодировать токен длиной {len(token)}: '{token[:20]}...'")
    
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

@app.api_route("/api/billing/{path:path}", methods=["GET", "POST", "PUT", "DELETE"], operation_id="proxy_billing")
async def proxy_to_billing(request: Request, path: str, user_id: str = Depends(verify_token)):
    target_url = f"{settings.BILLING_SERVICE_URL}/{path}"
    
    headers = dict(request.headers)
    headers["X-User-Id"] = user_id
    headers.pop("host", None)
    headers.pop("content-length", None)
    
    response = await http_client.request(
        method=request.method,
        url=target_url,
        headers=headers,
        params=request.query_params,
        content=await request.body()
    )
    
    # ИСПРАВЛЕНИЕ: Возвращаем сырой ответ, а не форсируем .json()
    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=response.headers.get("content-type", "application/json")
    )

@app.api_route("/api/notifications/{path:path}", methods=["GET", "POST", "PUT", "DELETE"], operation_id="proxy_notifications")
async def proxy_to_notifications(request: Request, path: str, user_id: str = Depends(verify_token)):
    target_url = f"{settings.NOTIFICATION_SERVICE_URL}/{path}"
    
    headers = dict(request.headers)
    headers["X-User-Id"] = user_id
    headers.pop("host", None)
    headers.pop("content-length", None)
    
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
        media_type=response.headers.get("content-type", "application/json")
    )

@app.get("/health")
async def health_check():
    return {"status": "API Gateway is running"}
