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
    es_voluntario: bool = False

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

def get_disponible_ahorro(cur, hogar_id: int, user_id: int):
    mes = datetime.date.today().month
    anio = datetime.date.today().year
    cur.execute("""
        SELECT COALESCE(SUM(importe), 0)
        FROM ingresos
        WHERE hogar_id = %s AND mes = %s AND anio = %s
    """, (hogar_id, mes, anio))
    ingreso_total = float(cur.fetchone()[0])
    cur.execute("""
        SELECT porcentaje_ahorro FROM presupuesto_hogar
        WHERE hogar_id = %s AND mes = %s AND anio = %s
    """, (hogar_id, mes, anio))
    presupuesto = cur.fetchone()
    pct_ahorro = float(presupuesto[0]) if presupuesto else 20.0
    return ingreso_total * pct_ahorro / 100

def get_disponible_mesada(cur, user_id: int, hogar_id: int):
    mes = datetime.date.today().month
    anio = datetime.date.today().year

    cur.execute("""
        SELECT COALESCE(SUM(importe), 0)
        FROM ingresos WHERE hogar_id = %s AND mes = %s AND anio = %s
    """, (hogar_id, mes, anio))
    ingreso_total = float(cur.fetchone()[0])

    cur.execute("""
        SELECT porcentaje_ahorro FROM presupuesto_hogar
        WHERE hogar_id = %s AND mes = %s AND anio = %s
    """, (hogar_id, mes, anio))
    presupuesto = cur.fetchone()
    pct_ahorro = float(presupuesto[0]) if presupuesto else 20.0

    monto_ahorro = ingreso_total * pct_ahorro / 100
    tras_ahorro = ingreso_total - monto_ahorro

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
def get_ahorros(user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT hogar_id FROM hogar_miembros WHERE usuario_id = %s", (user_id,))
    hogar = cur.fetchone()
    hogar_id = hogar[0] if hogar else None

    disponible = get_disponible_ahorro(cur, hogar_id, user_id) if hogar_id else 0.0

    if hogar_id:
        cur.execute("""
            SELECT id, nombre, meta, acumulado, mes, anio
            FROM ahorro WHERE hogar_id = %s
            ORDER BY creado_en DESC
        """, (hogar_id,))
    else:
        cur.execute("""
            SELECT id, nombre, meta, acumulado, mes, anio
            FROM ahorro WHERE usuario_id = %s
            ORDER BY creado_en DESC
        """, (user_id,))

    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {
        "disponible_para_ahorrar": disponible,
        "fondos": [{
            "id": r[0],
            "nombre": r[1],
            "meta": float(r[2]) if r[2] else None,
            "acumulado": float(r[3]),
            "progreso": round(float(r[3]) / float(r[2]) * 100, 1) if r[2] and float(r[2]) > 0 else 0,
            "mes": r[4],
            "anio": r[5]
        } for r in rows]
    }

@router.post("/")
def crear_ahorro(data: AhorroRequest, user_id: int = Depends(get_user)):
    mes = datetime.date.today().month
    anio = datetime.date.today().year
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT hogar_id FROM hogar_miembros WHERE usuario_id = %s", (user_id,))
    hogar = cur.fetchone()
    hogar_id = hogar[0] if hogar else None

    cur.execute("""
        INSERT INTO ahorro (hogar_id, usuario_id, nombre, meta, mes, anio)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
    """, (hogar_id, user_id, data.nombre, data.meta, mes, anio))
    ahorro_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Fondo de ahorro creado", "id": ahorro_id}

@router.put("/{ahorro_id}")
def actualizar_ahorro(ahorro_id: int, data: ActualizarAhorroRequest, user_id: int = Depends(get_user)):
    mes = datetime.date.today().month
    anio = datetime.date.today().year
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT hogar_id FROM hogar_miembros WHERE usuario_id = %s", (user_id,))
    hogar = cur.fetchone()
    hogar_id = hogar[0] if hogar else None

    if not data.es_voluntario:
        disponible_ahorro = get_disponible_ahorro(cur, hogar_id, user_id) if hogar_id else 999999.0
        if data.cantidad > disponible_ahorro:
            raise HTTPException(
                status_code=400,
                detail=f"Ya alcanzaste el límite de ahorro del mes. Disponible: {disponible_ahorro:.2f}€."
            )
    else:
        if hogar_id:
            disponible_mesada = get_disponible_mesada(cur, user_id, hogar_id)
            if data.cantidad > disponible_mesada:
                raise HTTPException(
                    status_code=400,
                    detail=f"No tienes suficiente mesada disponible. Disponible: {disponible_mesada:.2f}€"
                )
            cur.execute("""
                INSERT INTO ahorro_voluntario (usuario_id, hogar_id, fondo_id, cantidad, mes, anio)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (user_id, hogar_id, ahorro_id, data.cantidad, mes, anio))

    # Verificar que el fondo pertenece al usuario o su hogar
    if hogar_id:
        cur.execute("""
            UPDATE ahorro SET acumulado = acumulado + %s
            WHERE id = %s AND hogar_id = %s
            RETURNING acumulado, meta
        """, (data.cantidad, ahorro_id, hogar_id))
    else:
        cur.execute("""
            UPDATE ahorro SET acumulado = acumulado + %s
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
        "mensaje": "Ahorro actualizado",
        "acumulado": float(row[0]),
        "listo": float(row[0]) >= float(row[1]) if row[1] else False
    }

@router.delete("/{ahorro_id}")
def eliminar_ahorro(ahorro_id: int, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)
    cur.execute("DELETE FROM ahorro WHERE id = %s AND hogar_id = %s", (ahorro_id, hogar_id))
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Fondo de ahorro eliminado"}

@router.get("/disponible")
def get_disponible(user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)
    disponible = get_disponible_ahorro(cur, hogar_id, user_id)
    cur.close()
    conn.close()
    return {"disponible_para_ahorrar": disponible}