import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityAuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        client_ip = request.client.host if request.client else "unknown"
        
        response = await call_next(request)
        
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        response.headers["X-Security-Policy"] = "Eivanta-Zero-Trust"
        
        if response.status_code in [401, 403, 429]:
            print(f"[SECURITY ALERT] Unauthorized access attempt from IP {client_ip} on path {request.url.path}")
            
        return response
