from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fakeredis import FakeAsyncRedis
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app import models  # noqa: F401
from app.core.clock import FakeClock
from app.core.crypto import generate_fernet_key
from app.core.hashing import TEST_ARGON2_PARAMS, SecretHasher
from app.core.jwt import JwtKeys, JwtService
from app.db.base import Base


@compiles(UUID, "sqlite")
def compile_uuid_for_sqlite(*_args, **_kwargs) -> str:
    return "CHAR(32)"


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(*_args, **_kwargs) -> str:
    return "JSON"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 11, 9, 12, 0, tzinfo=UTC))


@pytest.fixture
def hasher() -> SecretHasher:
    return SecretHasher(TEST_ARGON2_PARAMS, pin_pepper="test-pin-pepper-not-for-prod")


@pytest.fixture
async def redis():
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
def jwt_service(clock: FakeClock) -> JwtService:
    return JwtService(
        issuer="dazu-pos-test",
        staff=JwtKeys(
            current_kid="v2",
            secrets={
                "v1": "staff-secret-v1-xxxxxxxxxxxxxxxx",
                "v2": "staff-secret-v2-xxxxxxxxxxxxxxxx",
            },
        ),
        admin=JwtKeys(
            current_kid="v1", secrets={"v1": "admin-secret-v1-xxxxxxxxxxxxxxxx"}
        ),
        signup=JwtKeys(
            current_kid="v1", secrets={"v1": "signup-secret-v1-xxxxxxxxxxxxxxx"}
        ),
        reset=JwtKeys(
            current_kid="v1", secrets={"v1": "reset-secret-v1-xxxxxxxxxxxxxxxx"}
        ),
        clock=clock,
    )


@pytest.fixture
def fernet_key() -> str:
    return generate_fernet_key()


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()
