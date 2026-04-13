"""FastAPI dependencies."""

from fastapi import Request


async def get_pool(request: Request):
    return request.app.state.pg_pool
