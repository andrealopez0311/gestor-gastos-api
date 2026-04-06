from fastapi import APIRouter, HTTPException, Header
from database import get_connection
from auth import hash_password, verify_password, create_token, decode_token
from pydantic import BaseModel

router = APIRouter(prefix="/usuarios", tags=["usuarios"])

class RegisterRequest(BaseModel):
    nombre: str
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

@router.post("/registro")
def registro(data: RegisterRequest):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM usuarios WHERE email = %s", (data.email,))
    if cur.fetchone():
        raise HTTPException(status_code=400, detail="Email ya registrado")
    cur.execute(
        "INSERT INTO usuarios (nombre, email, password_hash) VALUES (%s, %s, %s) RETURNING id",
        (data.nombre, data.email, hash_password(data.password))
    )
    user_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Usuario creado", "id": user_id}

@router.post("/login")
def login(data: LoginRequest):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, password_hash FROM usuarios WHERE email = %s", (data.email,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    if not user or not verify_password(data.password, user[1]):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")
    token = create_token({"sub": str(user[0])})
    return {"access_token": token, "token_type": "bearer"}