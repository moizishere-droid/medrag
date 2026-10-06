"""Password login, revocable tokens, ownership checks and shared rate limits."""
import hashlib
import hmac
import secrets
import time
from fastapi import HTTPException

SESSION_COOKIE = "medrag_session"


def request_token(request):
    authorization = request.headers.get("Authorization")
    if authorization:
        return authorization.partition(" ")[2]
    return request.cookies.get(SESSION_COOKIE, "")


def set_session_cookie(response, token, hours, secure=False):
    response.set_cookie(SESSION_COOKIE, token, max_age=hours * 3600,
                        httponly=True, secure=secure, samesite="lax", path="/")


def password_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1,
                            dklen=64, maxmem=64 * 1024 * 1024)
    return f"scrypt:{salt.hex()}:{digest.hex()}"


def password_matches(password, stored):
    try:
        scheme, salt, digest = stored.split(":")
        return scheme == "scrypt" and hmac.compare_digest(password_hash(password, bytes.fromhex(salt)), stored)
    except (ValueError, TypeError):
        return False


def rate_limit(conn, key, limit):
    """An atomic shared fixed-window limit, including failed login attempts."""
    window = int(time.time()) // 60
    with conn.cursor() as cur:
        cur.execute("DELETE FROM request_limits WHERE window_start < %s", (window - 60,))
        cur.execute("""INSERT INTO request_limits (bucket_key, window_start, attempts)
            VALUES (%s, %s, 1) ON CONFLICT (bucket_key, window_start)
            DO UPDATE SET attempts = request_limits.attempts + 1
            WHERE request_limits.attempts < %s RETURNING attempts""", (key, window, limit))
        if cur.fetchone() is None:
            raise HTTPException(status_code=429, detail="Too many requests. Please wait and retry.",
                                headers={"Retry-After": str(60 - int(time.time()) % 60)})


def issue_token(conn, user_id, hours):
    token = secrets.token_urlsafe(32)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM auth_tokens WHERE expires_at <= now()")
        cur.execute("INSERT INTO auth_tokens (token_hash, user_id, expires_at) VALUES (%s, %s, now() + %s * interval '1 hour')",
                    (hashlib.sha256(token.encode()).hexdigest(), user_id, hours))
    return token


def token_owner(conn, authorization):
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 128:
        raise HTTPException(status_code=401, detail="Please sign in.", headers={"WWW-Authenticate": "Bearer"})
    with conn.cursor() as cur:
        cur.execute("SELECT user_id FROM auth_tokens WHERE token_hash = %s AND expires_at > now()", (hashlib.sha256(token.encode()).hexdigest(),))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Sign-in expired. Please sign in again.", headers={"WWW-Authenticate": "Bearer"})
    return str(row[0])


def owns_session(conn, session_id, user_id):
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM sessions WHERE session_id = %s AND user_id = %s", (session_id, user_id))
        return cur.fetchone() is not None
