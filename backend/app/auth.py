"""
API Authentication Module.

Provides secure API key verification for DisasterMesh backend endpoints.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", description="API Key for authentication")


async def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """
    Verify that the provided API key is valid.

    Parameters
    ----------
    api_key : str
        The API key from the X-API-Key header

    Returns
    -------
    str
        The valid API key

    Raises
    ------
    HTTPException
        If the API key is invalid or missing
    """
    from app.config import get_settings

    settings = get_settings()
    if not settings.api_key:
        logger.warning("API_KEY not configured in settings")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server configuration error",
        )

    if api_key != settings.api_key:
        logger.warning("Invalid API key attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )

    return api_key
