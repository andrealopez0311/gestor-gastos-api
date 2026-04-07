from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from database import get_connection
from auth import decode_token
from pydantic import BaseModel
from typing import Optional
import datetime

router = APIRouter(prefix="/ahorro-personal", tags=["ahorro-personal"])
security = HTTPBearer()

class AhorroPersonalRequest(BaseModel):
    nombre: str
    meta: Optional[float] = None

class AnadirAhorroPersonalRequest(BaseModel):
    cantidad: float

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

def get_disponible_mesada(cur, user_id: int, hogar_id):
    mes = datetime.date.today().month
    anio = datetime.date.today().year

    if hogar_id:
        cur.execute("""
            SELECT COALESCE(SUM(importe), 0)
            FROM ingresos WHERE hogar_id = %s AND mes = %s AND anio = %s
        """, (hogar_id, mes, anio))
    else:
        cur.execute("""
            SELECT COALESCE(SUM(importe), 0)
            FROM ingresos WHERE usuario_id = %s AND mes = %s AND anio = %s
        """, (user_id, mes, anio))
    ingreso_total = float(cur.fetchone()[0])

    cur.execute("""
        SELECT porcentaje_ahorro FROM presupuesto_hogar
        WHERE hogar_id IS NOT DISTINCT FROM %s AND mes = %s AND anio = %s
    """, (hogar_id, mes, anio))
    presupuesto = cur.fetchone()
    pct_ahorro = float(presupuesto[0]) if presupuesto else 20.0

    monto_ahorro = ingreso_total * pct_ahorro / 100
    tras_ahorro = ingreso_total - monto_ahorro

    gastos_comunes = 0.0
    periodicos = 0.0
    if hogar_id:
        cur.execute("""
            SELECT COALESCE(SUM(importe), 0) FROM gastos_comunes
            WHERE hogar_id = %s
            AND DATE_TRUNC('month', fecha) = DATE_TRUNC('month', CURRENT_DATE)
        """, (hogar_id,))
        gastos_comunes = float(cur.fetchone()[0])

        cur.execute("""
            SELECT COALESCE(SUM(reserva_mensual), 0)
            FROM gastos_periodicos WHERE hogar_id = %s
        """, (hogar_id,))
        periodicos = float(cur.fetchone()[0])
    else:
        cur.execute("""
            SELECT COALESCE(SUM(importe), 0) FROM gastos_comunes
            WHERE usuario_id = %s AND hogar_id IS NULL
            AND DATE_TRUNC('month', fecha) = DATE_TRUNC('month', CURRENT_DATE)
        """, (user_id,))
        gastos_comunes = float(cur.fetchone()[0])

        cur.execute("""
            SELECT COALESCE(SUM(reserva_mensual), 0)
            FROM gastos_periodicos WHERE usuario_id = %s AND hogar_id IS NULL
        """, (user_id,))
        periodicos = float(cur.fetchone()[0])

    num_miembros = 1
    if hogar_id:
        cur.execute("SELECT COUNT(*) FROM hogar_miembros WHERE hogar_id = %s", (hogar_id,))
        num_miembros = cur.fetchone()[0]

    mesada = (tras_ahorro - gastos_comunes - periodicos) / num_miembros if num_miembros > 0 else 0

    cur.execute("""
        SELECT COALESCE(SUM(importe), 0) FROM gastos
        WHERE usuario_id = %s
        AND DATE_TRUNC('month', fecha) = DATE_TRUNC('month', CURRENT_DATE)
    """, (user_id,))
    gastos_personales = float(cur.fetchone()[0])

    cur.execute("""
        SELECT COALESCE(SUM(acumulado), 0)
        FROM ahorro_personal WHERE usuario_id = %s
    """, (user_id,))
    ahorro_personal = float(cur.fetchone()[0])

    cur.execute("""
        SELECT COALESCE(SUM(cantidad), 0)
        FROM ahorro_voluntario
        WHERE usuario_id = %s AND mes = %s AND anio = %s
    """, (user_id, mes, anio))
    ahorro_voluntario = float(cur.fetchone()[0])

    return mesada - gastos_personales - ahorro_personal - ahorro_voluntario

@router.get("/")
def get_ahorros_personales(user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id_opcional(cur, user_id)
    disponible = get_disponible_mesada(cur, user_id, hogar_id)

    cur.execute("""
        SELECT id, nombre, meta, acumulado
        FROM ahorro_personal
        WHERE usuario_id = %s
        ORDER BY creado_en DESC
    """, (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return {
        "disponible_mesada": disponible,
        "fondos": [{
            "id": r[0],
            "nombre": r[1],
            "meta": float(r[2]) if r[2] else None,
            "acumulado": float(r[3]),
            "progreso": round(float(r[3]) / float(r[2]) * 100, 1) if r[2] and float(r[2]) > 0 else 0
        } for r in rows]
    }

@router.post("/")
def crear_ahorro_personal(data: AhorroPersonalRequest, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO ahorro_personal (usuario_id, nombre, meta)
        VALUES (%s, %s, %s) RETURNING id
    """, (user_id, data.nombre, data.meta))
    ahorro_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Fondo personal creado", "id": ahorro_id}

@router.put("/{ahorro_id}")
def anadir_ahorro_personal(ahorro_id: int, data: AnadirAhorroPersonalRequest, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id_opcional(cur, user_id)

    disponible = get_disponible_mesada(cur, user_id, hogar_id)
    if data.cantidad > disponible:
        raise HTTPException(
            status_code=400,
            detail=f"No puedes ahorrar más de tu mesada disponible. Disponible: {disponible:.2f}€"
        )

    cur.execute("""
        UPDATE ahorro_personal
        SET acumulado = acumulado + %s
        WHERE id = %s AND usuario_id = %s
        RETURNING acumulado, meta
    """, (data.cantidad, ahorro_id, user_id))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Fondo no encontrado")
    conn.commit()
    cur.close()
    conn.close()
    return {
        "mensaje": "Ahorro personal actualizado",
        "acumulado": float(row[0]),
        "listo": float(row[0]) >= float(row[1]) if row[1] else False
    }

@router.delete("/{ahorro_id}")
def eliminar_ahorro_personal(ahorro_id: int, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM ahorro_personal WHERE id = %s AND usuario_id = %s", (ahorro_id, user_id))
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Fondo personal eliminado"}