from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import Response, FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError, ExpiredSignatureError
import httpx
from settings import settings
from logging import getLogger
from prometheus_fastapi_instrumentator import Instrumentator

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

import websockets
from fastapi import WebSocket, WebSocketDisconnect

# Хэндлер для WebSocket-соединений Grafana
@app.websocket("/api/grafana/api/live/ws")
async def proxy_grafana_websocket(websocket: WebSocket):
    await websocket.accept()
    
    # Внутренний адрес WebSocket Grafana в контейнере
    # Обратите внимание: используем ws:// вместо http://
    target_ws_url = "ws://grafana:3000/api/grafana/api/live/ws"
    
    try:
        # Подключаемся к Grafana изнутри шлюза
        async with websockets.connect(target_ws_url) as target_ws:
            
            # Фоновая задача для пересылки сообщений ИЗ Grafana В браузер
            async def forward_to_browser():
                try:
                    async for message in target_ws:
                        await websocket.send_text(message) # type: ignore
                except Exception:
                    pass

            import asyncio
            asyncio.create_task(forward_to_browser())

            # Читаем сообщения ИЗ браузера и шлем В Grafana
            async for message in websocket.iter_text():
                await target_ws.send(message)
                
    except WebSocketDisconnect:
        logger.info("Браузер отключился от WebSocket Grafana")
    except Exception as e:
        logger.error(f"Ошибка WebSocket прокси Grafana: {e}")

# --- Выделенный прозрачный роут для Grafana (СТРОГО ВЫШЕ общего прокси) ---
@app.api_route("/api/grafana/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_to_grafana_isolated(request: Request, path: str):
    # Достаем базовый URL Grafana из настроек
    base_url = settings.SERVICES_URLS.get("grafana", "http://grafana:3000")
    
    # ВАЖНО: Так как в Grafana включен SERVE_FROM_SUB_PATH, 
    # мы ОБЯЗАНЫ передавать внутренний путь вместе с префиксом /api/grafana/
    target_url = f"{base_url}/api/grafana/{path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    # Копируем заголовки, подменяя Host для внутренней докер-сети
    headers = dict(request.headers)
    headers["host"] = base_url.replace("http://", "").replace("https://", "")
    headers.pop("content-length", None)
    
    try:
        response = await http_client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=await request.body(),
            follow_redirects=False # Не даем httpx самому ходить по редиректам
        )
        
        # Создаем чистый ответ
        gateway_response = Response(
            content=response.content,
            status_code=response.status_code,
            media_type=response.headers.get("content-type", "application/json")
        )
        
        # Переносим ВСЕ заголовки (включая множественные Set-Cookie и Location для редиректов)
        for key, value in response.headers.raw:
            k = key.decode("utf-8").lower()
            v = value.decode("utf-8")
            if k in ["content-length", "transfer-encoding"]:
                continue
            if k == "set-cookie":
                gateway_response.headers.append(k, v)
            else:
                gateway_response.headers[k] = v

        return gateway_response

    except httpx.RequestError as exc:
        logger.error(f"Ошибка проксирования к Grafana: {exc}")
        raise HTTPException(status_code=502, detail="Grafana недоступна")

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
        
        # 1. Создаем базовый ответ
        gateway_response = Response(
            content=response.content,
            status_code=response.status_code,
            media_type=response.headers.get("content-type", "application/json")
        )
        
        # 2. Переносим заголовки, аккуратно обрабатывая дубликаты (особенно Set-Cookie)
        # В httpx.Response заголовки хранятся в специальном регистронезависимом виде, 
        # где через `.raw` можно достать все дублирующиеся ключи.
        for key, value in response.headers.raw:
            k = key.decode("utf-8").lower()
            v = value.decode("utf-8")
            
            if k in ["content-length", "transfer-encoding"]:
                continue
                
            # Если это кука, добавляем её через метод append, чтобы заголовки не затирались
            if k == "set-cookie":
                gateway_response.headers.append(k, v)
            else:
                gateway_response.headers[k] = v

        return gateway_response

    except httpx.RequestError as exc:
        logger.error(f"Ошибка проксирования к {target_url}: {exc}")
        raise HTTPException(status_code=502, detail=f"Не удалось связаться с сервисом '{service_name}'")

@app.get("/health", include_in_schema=False)
async def health_check():
    return {"status": "ok"}

Instrumentator().instrument(app).expose(app)