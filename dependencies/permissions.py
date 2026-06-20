from fastapi import Depends, HTTPException, WebSocket
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase

from core.auth import UserManager, current_active_user, get_jwt_strategy , fastapi_users, get_user_manager
from app.db.models import User, get_async_session
import uuid
from sqlalchemy.ext.asyncio import AsyncSession


async def require_user(user: User = Depends(current_active_user)):
    if user.role != "user":
        raise HTTPException(status_code=403, detail="User access required")
    return user

import jwt
from fastapi import Query
from core.auth import SECRET

async def require_user_ws(
    websocket: WebSocket, 
    token: str = Query(None),
    session: AsyncSession = Depends(get_async_session)
) -> User:
    """Authenticate WebSocket connection and return user"""
    if not token:
        await websocket.close(code=1008, reason="Missing token query parameter")
        return None

    try:
        payload = jwt.decode(
            token, 
            SECRET, 
            audience="fastapi-users:auth", 
            algorithms=["HS256"]
        )
        user_id = uuid.UUID(payload["sub"])
    except Exception as e:
        await websocket.close(code=1008, reason=str(e))
        return None

    user_db = SQLAlchemyUserDatabase(session, User)
    user_manager = UserManager(user_db)
    try:
        user = await user_manager.get(user_id)
    except Exception:
        await websocket.close(code=1008, reason="User not found")
        return None

    if not user or not user.is_active:
        await websocket.close(code=1008, reason="User is inactive")
        return None

    return user

async def require_mechanic(user: User = Depends(current_active_user)):
    if user.role != "mechanic":
        raise HTTPException(status_code=403, detail="Mechanic access required")
    return user

async def require_admin(user: User = Depends(current_active_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")  
    return user

async def require_mechanic_or_user(user: User = Depends(current_active_user)):
    if user.role not in ("mechanic" , "user"):
        raise HTTPException(status_code=403, detail="Access required")
    return user
