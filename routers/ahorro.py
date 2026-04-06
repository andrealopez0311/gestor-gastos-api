from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from database import get_connection
from auth import decode_token
from pydantic import BaseModel
from typing import Optional
import datetime

router = APIRouter(prefix="/ahorro", tags=["ahorro"])
security = HTTPBearer()

class AhorroRequest(BaseModel):
    nombre: str
    meta: Optional[float] = None

class ActualizarAhorroRequest(BaseModel):
    cantidad: float

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

@router.get("/")
def get_ahorros(user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)
    cur.execute("""
        SELECT id, nombre, meta, acumulado, mes, anio
        FROM ahorro
        WHERE hogar_id = %s
        ORDER BY creado_en DESC
    """, (hogar_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{
        "id": r[0],
        "nombre": r[1],
        "meta": float(r[2]) if r[2] else None,
        "acumulado": float(r[3]),
        "progreso": round(float(r[3]) / float(r[2]) * 100, 1) if r[2] and float(r[2]) > 0 else 0,
        "mes": r[4],
        "anio": r[5]
    } for r in rows]

@router.post("/")
def crear_ahorro(data: AhorroRequest, user_id: int = Depends(get_user)):
    mes = datetime.date.today().month
    anio = datetime.date.today().year
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)
    cur.execute("""
        INSERT INTO ahorro (hogar_id, nombre, meta, mes, anio)
        VALUES (%s, %s, %s, %s, %s) RETURNING id
    """, (hogar_id, data.nombre, data.meta, mes, anio))
    ahorro_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Fondo de ahorro creado", "id": ahorro_id}

@router.put("/{ahorro_id}")
def actualizar_ahorro(ahorro_id: int, data: ActualizarAhorroRequest, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)
    cur.execute("""
        UPDATE ahorro
        SET acumulado = acumulado + %s
        WHERE id = %s AND hogar_id = %s
    """, (data.cantidad, ahorro_id, hogar_id))
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Ahorro actualizado"}

@router.delete("/{ahorro_id}")
def eliminar_ahorro(ahorro_id: int, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)
    cur.execute("""
        DELETE FROM ahorro WHERE id = %s AND hogar_id = %s
    """, (ahorro_id, hogar_id))
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Fondo de ahorro eliminado"}