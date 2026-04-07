from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from database import get_connection
from auth import decode_token
from pydantic import BaseModel
from typing import Optional
import datetime

router = APIRouter(prefix="/ingresos", tags=["ingresos"])
security = HTTPBearer()

class IngresoRequest(BaseModel):
    importe: float
    descripcion: Optional[str] = ""
    fuente: Optional[str] = ""
    mes: Optional[int] = None
    anio: Optional[int] = None

class EliminarIngresoRequest(BaseModel):
    ingreso_id: int

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
def crear_ingreso(data: IngresoRequest, user_id: int = Depends(get_user)):
    mes = data.mes or datetime.date.today().month
    anio = data.anio or datetime.date.today().year
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)

    # Ahora permitimos múltiples ingresos por mes
    cur.execute("""
        INSERT INTO ingresos (usuario_id, hogar_id, importe, descripcion, fuente, mes, anio)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
    """, (user_id, hogar_id, data.importe, data.descripcion, data.fuente, mes, anio))
    ingreso_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Ingreso registrado", "id": ingreso_id}

@router.delete("/{ingreso_id}")
def eliminar_ingreso(ingreso_id: int, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        DELETE FROM ingresos WHERE id = %s AND usuario_id = %s
    """, (ingreso_id, user_id))
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Ingreso eliminado"}

@router.get("/")
def get_mis_ingresos(user_id: int = Depends(get_user)):
    mes = datetime.date.today().month
    anio = datetime.date.today().year
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, importe, descripcion, fuente, mes, anio
        FROM ingresos
        WHERE usuario_id = %s AND mes = %s AND anio = %s
        ORDER BY id DESC
    """, (user_id, mes, anio))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"id": r[0], "importe": float(r[1]), "descripcion": r[2], "fuente": r[3], "mes": r[4], "anio": r[5]} for r in rows]

@router.get("/hogar")
def get_ingresos_hogar(user_id: int = Depends(get_user)):
    mes = datetime.date.today().month
    anio = datetime.date.today().year
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)
    cur.execute("""
        SELECT u.nombre, i.importe, i.descripcion, i.fuente, i.id
        FROM ingresos i
        JOIN usuarios u ON i.usuario_id = u.id
        WHERE i.hogar_id = %s AND i.mes = %s AND i.anio = %s
        ORDER BY i.id DESC
    """, (hogar_id, mes, anio))
    rows = cur.fetchall()
    total = sum(float(r[1]) for r in rows)
    cur.close()
    conn.close()
    return {
        "total": total,
        "ingresos": [{"nombre": r[0], "importe": float(r[1]), "descripcion": r[2], "fuente": r[3], "id": r[4]} for r in rows]
    }