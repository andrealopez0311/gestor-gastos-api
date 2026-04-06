from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from database import get_connection
from auth import decode_token
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/hogares", tags=["hogares"])
security = HTTPBearer()

class HogarRequest(BaseModel):
    nombre: str

class InvitarRequest(BaseModel):
    email: str

def get_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    user_id = decode_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="No autorizado")
    return int(user_id)

def get_hogar_id(cur, user_id: int):
    cur.execute("SELECT hogar_id FROM hogar_miembros WHERE usuario_id = %s", (user_id,))
    hogar = cur.fetchone()
    if not hogar:
        raise HTTPException(status_code=400, detail="No perteneces a ningún hogar")
    return hogar[0]

@router.post("/")
def crear_hogar(data: HogarRequest, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT h.id FROM hogares h
        JOIN hogar_miembros hm ON h.id = hm.hogar_id
        WHERE hm.usuario_id = %s
    """, (user_id,))
    if cur.fetchone():
        raise HTTPException(status_code=400, detail="Ya perteneces a un hogar")
    cur.execute(
        "INSERT INTO hogares (nombre, creador_id) VALUES (%s, %s) RETURNING id",
        (data.nombre, user_id)
    )
    hogar_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO hogar_miembros (hogar_id, usuario_id, rol) VALUES (%s, %s, 'admin')",
        (hogar_id, user_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Hogar creado", "id": hogar_id}

@router.get("/mio")
def get_mi_hogar(user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT h.id, h.nombre, h.creador_id
        FROM hogares h
        JOIN hogar_miembros hm ON h.id = hm.hogar_id
        WHERE hm.usuario_id = %s
    """, (user_id,))
    hogar = cur.fetchone()
    if not hogar:
        cur.close()
        conn.close()
        return {"hogar": None}
    cur.execute("""
        SELECT u.id, u.nombre, u.email, hm.rol
        FROM usuarios u
        JOIN hogar_miembros hm ON u.id = hm.usuario_id
        WHERE hm.hogar_id = %s
    """, (hogar[0],))
    miembros = cur.fetchall()
    cur.close()
    conn.close()
    return {
        "hogar": {"id": hogar[0], "nombre": hogar[1], "creador_id": hogar[2]},
        "miembros": [{"id": m[0], "nombre": m[1], "email": m[2], "rol": m[3]} for m in miembros]
    }

@router.post("/invitar")
def invitar_miembro(data: InvitarRequest, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)
    cur.execute("SELECT id FROM usuarios WHERE email = %s", (data.email,))
    invitado = cur.fetchone()
    if not invitado:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    invitado_id = invitado[0]
    cur.execute("""
        SELECT id FROM hogar_miembros WHERE hogar_id = %s AND usuario_id = %s
    """, (hogar_id, invitado_id))
    if cur.fetchone():
        raise HTTPException(status_code=400, detail="Ya es miembro del hogar")
    cur.execute(
        "INSERT INTO hogar_miembros (hogar_id, usuario_id, rol) VALUES (%s, %s, 'miembro')",
        (hogar_id, invitado_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Miembro añadido correctamente"}

@router.get("/miembros")
def get_miembros(user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT u.id, u.nombre, u.email, hm.rol
        FROM usuarios u
        JOIN hogar_miembros hm ON u.id = hm.usuario_id
        WHERE hm.hogar_id = (
            SELECT hogar_id FROM hogar_miembros WHERE usuario_id = %s
        )
    """, (user_id,))
    miembros = cur.fetchall()
    cur.close()
    conn.close()
    return [{"id": m[0], "nombre": m[1], "email": m[2], "rol": m[3]} for m in miembros]