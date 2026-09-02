import os
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# SEC-03 SAST (28 Aug 2026, bandit B105): this module is NOT wired into the
# live app -- nothing under backend/ imports backend.app.core.security or
# calls verify_zero_trust_token (confirmed by grep), and `python-jose`
# (the `jose` import above) isn't even in requirements.txt or installed,
# so this module cannot actually run as written today. That made the
# hardcoded SECRET_KEY that used to be here a landmine rather than a live
# vulnerability -- unreachable now, but a real, predictable JWT signing
# key that would silently reactivate the moment anyone ever wires this
# module into a router. Fixed the same way backend/auth.py's real,
# currently-used JWT_SECRET already works, rather than leaving a
# hardcoded fallback here for someone to copy-paste forward. This module
# is otherwise untouched -- whether to delete it outright (it appears to
# duplicate backend/auth.py's real, live implementation) or fix its
# missing `jose` dependency and actually wire it in is a real call this
# pass isn't making unilaterally.
SECRET_KEY = os.environ.get("ZERO_TRUST_SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

security_scheme = HTTPBearer()

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def verify_zero_trust_token(credentials: HTTPAuthorizationCredentials = Depends(security_scheme)):
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate zero-trust security credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        return payload
    except JWTError:
        raise credentials_exception
