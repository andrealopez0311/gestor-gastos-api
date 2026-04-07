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

def get_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    user_id = decode_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="No autorizado")
    return int(user_id)

def get_hogar_id_opcional(cur, user_id: int):
    cur.execute("SELECT hogar_id FROM hogar_miembros WHERE usuario_id = %s", (user_id,))
    hogar = cur.fetchone()
    return hogar[0] if hogar else None

@router.post("/")
def crear_ingreso(data: IngresoRequest, user_id: int = Depends(get_user)):
    mes = data.mes or datetime.date.today().month
    anio = data.anio or datetime.date.today().year
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id_opcional(cur, user_id)

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
    mes = datetime.date.today().month
    anio = datetime.date.today().year
    conn = get_connection()
    cur = conn.cursor()

    # Obtener importe del ingreso antes de eliminarlo
    cur.execute("""
        SELECT importe FROM ingresos
        WHERE id = %s AND usuario_id = %s
    """, (ingreso_id, user_id))
    ingreso = cur.fetchone()
    if not ingreso:
        raise HTTPException(status_code=404, detail="Ingreso no encontrado")
    importe = float(ingreso[0])

    # Calcular el porcentaje de ahorro configurado
    cur.execute("SELECT hogar_id FROM hogar_miembros WHERE usuario_id = %s", (user_id,))
    hogar = cur.fetchone()
    hogar_id = hogar[0] if hogar else None

    cur.execute("""
        SELECT porcentaje_ahorro FROM presupuesto_hogar
        WHERE hogar_id IS NOT DISTINCT FROM %s AND mes = %s AND anio = %s
    """, (hogar_id, mes, anio))
    presupuesto = cur.fetchone()
    pct_ahorro = float(presupuesto[0]) if presupuesto else 20.0
    monto_ahorro = importe * pct_ahorro / 100

    # Descontar el ahorro de los fondos
    if hogar_id:
        cur.execute("""
            UPDATE ahorro
            SET acumulado = GREATEST(0, acumulado - %s)
            WHERE hogar_id = %s
            AND id = (
                SELECT id FROM ahorro WHERE hogar_id = %s
                ORDER BY creado_en DESC LIMIT 1
            )
        """, (monto_ahorro, hogar_id, hogar_id))
    else:
        cur.execute("""
            UPDATE ahorro
            SET acumulado = GREATEST(0, acumulado - %s)
            WHERE usuario_id = %s
            AND id = (
                SELECT id FROM ahorro WHERE usuario_id = %s
                ORDER BY creado_en DESC LIMIT 1
            )
        """, (monto_ahorro, user_id, user_id))

    # Eliminar el ingreso
    cur.execute("DELETE FROM ingresos WHERE id = %s AND usuario_id = %s", (ingreso_id, user_id))
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Ingreso eliminado y ahorro ajustado"}

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
    hogar_id = get_hogar_id_opcional(cur, user_id)

    if hogar_id:
        cur.execute("""
            SELECT u.nombre, i.importe, i.descripcion, i.fuente, i.id
            FROM ingresos i
            JOIN usuarios u ON i.usuario_id = u.id
            WHERE i.hogar_id = %s AND i.mes = %s AND i.anio = %s
            ORDER BY i.id DESC
        """, (hogar_id, mes, anio))
    else:
        cur.execute("""
            SELECT u.nombre, i.importe, i.descripcion, i.fuente, i.id
            FROM ingresos i
            JOIN usuarios u ON i.usuario_id = u.id
            WHERE i.usuario_id = %s AND i.mes = %s AND i.anio = %s
            ORDER BY i.id DESC
        """, (user_id, mes, anio))

    rows = cur.fetchall()
    total = sum(float(r[1]) for r in rows)
    cur.close()
    conn.close()
    return {
        "total": total,
        "ingresos": [{"nombre": r[0], "importe": float(r[1]), "descripcion": r[2], "fuente": r[3], "id": r[4]} for r in rows]
    }