from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routers.admin_auth import router as admin_auth_router
from app.api.routers.signup import router as signup_router
from app.api.routers.staff_auth import router as staff_auth_router
from app.core.config import get_settings
from app.core.errors import AuthError
from app.core.i18n import preferred_language
from app.db.redis import close_redis_client

settings = get_settings()

_ERROR_MESSAGES_SW = {
    "INVALID_CREDENTIALS": "Taarifa za uthibitishaji si sahihi.",
    "ACCOUNT_LOCKED": "Akaunti imefungwa kwa muda.",
    "DEVICE_REVOKED": "Kifaa hiki kimeondolewa.",
    "DEVICE_NOT_REGISTERED": "Kifaa hiki hakijasajiliwa.",
    "BUSINESS_SUSPENDED": "Biashara hii haiwezi kuingia kwa sasa.",
    "TOKEN_REUSED": "Tokeni ya kuingia imetumika tena.",
    "MFA_REQUIRED": "Uthibitishaji wa hatua mbili unahitajika.",
    "RATE_LIMITED": "Majaribio yamezidi. Tafadhali jaribu tena baadaye.",
    "OTP_INVALID": "Nambari ya uthibitisho si sahihi.",
    "OTP_EXPIRED": "Nambari ya uthibitisho imeisha muda.",
    "OTP_TOO_MANY_ATTEMPTS": "Majaribio yamezidi. Anza tena.",
    "WEAK_PASSWORD": "Nenosiri halikidhi masharti.",
    "WEAK_PIN": "PIN haikidhi masharti.",
    "VALIDATION_ERROR": "Taarifa ulizotuma si sahihi.",
    "SERVICE_UNAVAILABLE": "Huduma haipatikani kwa sasa. Tafadhali jaribu tena baadaye.",
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await close_redis_client()


app = FastAPI(
    title="Freshmart-Pos",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["x-frame-options"] = "DENY"
    response.headers["referrer-policy"] = "strict-origin-when-cross-origin"
    response.headers["permissions-policy"] = "geolocation=(), microphone=()"
    return response


app.include_router(signup_router, prefix="/api/v1")
app.include_router(staff_auth_router, prefix="/api/v1")
app.include_router(admin_auth_router, prefix="/api/v1")


@app.exception_handler(AuthError)
async def auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
    language = preferred_language(request.headers.get("accept-language"))
    message = (
        _ERROR_MESSAGES_SW.get(exc.code, exc.message)
        if language == "sw"
        else exc.message
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {"code": exc.code, "message": message, "details": exc.details}
        },
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    language = preferred_language(request.headers.get("accept-language"))
    errors = [
        {"location": list(error["loc"]), "type": error["type"], "message": error["msg"]}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": (
                    _ERROR_MESSAGES_SW["VALIDATION_ERROR"]
                    if language == "sw"
                    else "The request is invalid."
                ),
                "details": {"fields": errors},
            }
        },
    )


@app.get("/")
def read_root():
    return {"status": "success", "message": "FastAPI backend is running successfully!"}
