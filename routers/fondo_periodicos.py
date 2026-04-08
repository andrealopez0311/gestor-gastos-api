from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from database import get_connection
from auth import decode_token
from pydantic import BaseModel
import datetime

router = APIRouter(prefix="/fondo-periodicos", tags=["fondo-periodicos"])
security = HTTPBearer()

class CuotaRequest(BaseModel):
    gasto_periodico_id: int
    importe: float
    fecha_pago: str

class AportarFondoRequest(BaseModel):
    cantidad: float

def get_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    user_id = decode_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="No autorizado")
    return int(user_id)

@router.get("/")
def get_fondo(user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT hogar_id FROM hogar_miembros WHERE usuario_id = %s", (user_id,))
    hogar = cur.fetchone()
    hogar_id = hogar[0] if hogar else None

    # Reserva mensual total
    if hogar_id:
        cur.execute("""
            SELECT COALESCE(SUM(reserva_mensual), 0)
            FROM gastos_periodicos WHERE hogar_id = %s
        """, (hogar_id,))
    else:
        cur.execute("""
            SELECT COALESCE(SUM(reserva_mensual), 0)
            FROM gastos_periodicos WHERE usuario_id = %s AND hogar_id IS NULL
        """, (user_id,))
    reserva_mensual = float(cur.fetchone()[0])

    # Fecha del primer gasto periódico
    if hogar_id:
        cur.execute("SELECT MIN(creado_en) FROM gastos_periodicos WHERE hogar_id = %s", (hogar_id,))
    else:
        cur.execute("SELECT MIN(creado_en) FROM gastos_periodicos WHERE usuario_id = %s AND hogar_id IS NULL", (user_id,))
    primera_fecha = cur.fetchone()[0]

    hoy = datetime.date.today()
    meses = (hoy.year - primera_fecha.year) * 12 + (hoy.month - primera_fecha.month) + 1 if primera_fecha else 0

    # Acumulado teórico = reserva mensual * meses
    acumulado_teorico = reserva_mensual * meses

    # Aportaciones extra de la mesada
    if hogar_id:
        cur.execute("""
            SELECT COALESCE(SUM(acumulado), 0)
            FROM fondo_periodicos WHERE hogar_id = %s
        """, (hogar_id,))
    else:
        cur.execute("""
            SELECT COALESCE(SUM(acumulado), 0)
            FROM fondo_periodicos WHERE usuario_id = %s AND hogar_id IS NULL
        """, (user_id,))
    aportaciones_extra = float(cur.fetchone()[0])

    # Total pagado en cuotas
    if hogar_id:
        cur.execute("""
            SELECT COALESCE(SUM(cp.importe), 0)
            FROM cuotas_periodicas cp
            JOIN gastos_periodicos gp ON cp.gasto_periodico_id = gp.id
            WHERE gp.hogar_id = %s AND cp.pagada = TRUE
        """, (hogar_id,))
    else:
        cur.execute("""
            SELECT COALESCE(SUM(cp.importe), 0)
            FROM cuotas_periodicas cp
            JOIN gastos_periodicos gp ON cp.gasto_periodico_id = gp.id
            WHERE gp.usuario_id = %s AND gp.hogar_id IS NULL AND cp.pagada = TRUE
        """, (user_id,))
    total_pagado = float(cur.fetchone()[0])

    # Saldo = acumulado teórico + aportaciones extra - pagado
    saldo = acumulado_teorico + aportaciones_extra - total_pagado

    # Próximas cuotas pendientes
    if hogar_id:
        cur.execute("""
            SELECT cp.id, gp.nombre, cp.importe, cp.fecha_pago,
                   (cp.fecha_pago - CURRENT_DATE)
            FROM cuotas_periodicas cp
            JOIN gastos_periodicos gp ON cp.gasto_periodico_id = gp.id
            WHERE gp.hogar_id = %s AND cp.pagada = FALSE
            ORDER BY cp.fecha_pago ASC
        """, (hogar_id,))
    else:
        cur.execute("""
            SELECT cp.id, gp.nombre, cp.importe, cp.fecha_pago,
                   (cp.fecha_pago - CURRENT_DATE)
            FROM cuotas_periodicas cp
            JOIN gastos_periodicos gp ON cp.gasto_periodico_id = gp.id
            WHERE gp.usuario_id = %s AND gp.hogar_id IS NULL AND cp.pagada = FALSE
            ORDER BY cp.fecha_pago ASC
        """, (user_id,))
    cuotas = cur.fetchall()

    cur.close()
    conn.close()

    return {
        "saldo": saldo,
        "aportaciones_extra": aportaciones_extra,
        "reserva_mensual": reserva_mensual,
        "meses_acumulados": meses,
        "cuotas_pendientes": [{
            "id": r[0],
            "nombre": r[1],
            "importe": float(r[2]),
            "fecha_pago": str(r[3]),
            "dias_restantes": r[4].days if hasattr(r[4], 'days') else int(r[4]) if r[4] is not None else None,
            "alerta": (r[4].days <= 30 if hasattr(r[4], 'days') else int(r[4]) <= 30) if r[4] is not None else False,
            "cubierta": saldo >= float(r[2])
        } for r in cuotas]
    }

@router.post("/aportar")
def aportar_fondo(data: AportarFondoRequest, user_id: int = Depends(get_user)):
    mes = datetime.date.today().month
    anio = datetime.date.today().year
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT hogar_id FROM hogar_miembros WHERE usuario_id = %s", (user_id,))
    hogar = cur.fetchone()
    hogar_id = hogar[0] if hogar else None

    if hogar_id:
        cur.execute("""
            SELECT COALESCE(SUM(importe), 0) FROM ingresos
            WHERE hogar_id = %s AND mes = %s AND anio = %s
        """, (hogar_id, mes, anio))
    else:
        cur.execute("""
            SELECT COALESCE(SUM(importe), 0) FROM ingresos
            WHERE usuario_id = %s AND mes = %s AND anio = %s
        """, (user_id, mes, anio))
    ingreso_total = float(cur.fetchone()[0])

    cur.execute("""
        SELECT porcentaje_ahorro FROM presupuesto_hogar
        WHERE hogar_id IS NOT DISTINCT FROM %s AND mes = %s AND anio = %s
    """, (hogar_id, mes, anio))
    presupuesto = cur.fetchone()
    pct_ahorro = float(presupuesto[0]) if presupuesto else 20.0
    tras_ahorro = ingreso_total * (1 - pct_ahorro / 100)

    cur.execute("""
        SELECT COALESCE(SUM(importe), 0) FROM gastos
        WHERE usuario_id = %s
        AND DATE_TRUNC('month', fecha) = DATE_TRUNC('month', CURRENT_DATE)
    """, (user_id,))
    gastos_personales = float(cur.fetchone()[0])

    disponible = tras_ahorro - gastos_personales
    if data.cantidad > disponible:
        raise HTTPException(
            status_code=400,
            detail=f"No tienes suficiente mesada. Disponible: {disponible:.2f}€"
        )

    if hogar_id:
        cur.execute("""
            SELECT id FROM fondo_periodicos
            WHERE hogar_id = %s AND mes = %s AND anio = %s
        """, (hogar_id, mes, anio))
    else:
        cur.execute("""
            SELECT id FROM fondo_periodicos
            WHERE usuario_id = %s AND hogar_id IS NULL AND mes = %s AND anio = %s
        """, (user_id, mes, anio))
    fondo = cur.fetchone()

    if fondo:
        cur.execute("UPDATE fondo_periodicos SET acumulado = acumulado + %s WHERE id = %s",
                   (data.cantidad, fondo[0]))
    else:
        cur.execute("""
            INSERT INTO fondo_periodicos (hogar_id, usuario_id, acumulado, mes, anio)
            VALUES (%s, %s, %s, %s, %s)
        """, (hogar_id, user_id, data.cantidad, mes, anio))

    # Registrar como ahorro voluntario para descontarlo de la mesada
    cur.execute("""
        INSERT INTO ahorro_voluntario (usuario_id, hogar_id, fondo_id, cantidad, mes, anio)
        VALUES (%s, %s, NULL, %s, %s, %s)
    """, (user_id, hogar_id, data.cantidad, mes, anio))

    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Aportación registrada", "cantidad": data.cantidad}

@router.put("/cuotas/{cuota_id}/pagar")
def pagar_cuota(cuota_id: int, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT hogar_id FROM hogar_miembros WHERE usuario_id = %s", (user_id,))
    hogar = cur.fetchone()
    hogar_id = hogar[0] if hogar else None

    cur.execute("""
        SELECT cp.importe FROM cuotas_periodicas cp
        WHERE cp.id = %s AND cp.pagada = FALSE
    """, (cuota_id,))
    cuota = cur.fetchone()
    if not cuota:
        raise HTTPException(status_code=404, detail="Cuota no encontrada")
    importe = float(cuota[0])

    if hogar_id:
        cur.execute("""
            SELECT COALESCE(SUM(acumulado), 0)
            FROM fondo_periodicos WHERE hogar_id = %s
        """, (hogar_id,))
    else:
        cur.execute("""
            SELECT COALESCE(SUM(acumulado), 0)
            FROM fondo_periodicos WHERE usuario_id = %s AND hogar_id IS NULL
        """, (user_id,))
    acumulado = float(cur.fetchone()[0])

    if acumulado < importe:
        raise HTTPException(
            status_code=400,
            detail=f"Fondo insuficiente. Acumulado: {acumulado:.2f}€, necesitas: {importe:.2f}€"
        )

    if hogar_id:
        cur.execute("""
            UPDATE fondo_periodicos SET acumulado = acumulado - %s
            WHERE hogar_id = %s
            AND id = (SELECT id FROM fondo_periodicos WHERE hogar_id = %s ORDER BY creado_en DESC LIMIT 1)
        """, (importe, hogar_id, hogar_id))
    else:
        cur.execute("""
            UPDATE fondo_periodicos SET acumulado = acumulado - %s
            WHERE usuario_id = %s AND hogar_id IS NULL
            AND id = (SELECT id FROM fondo_periodicos WHERE usuario_id = %s AND hogar_id IS NULL ORDER BY creado_en DESC LIMIT 1)
        """, (importe, user_id, user_id))

    cur.execute("UPDATE cuotas_periodicas SET pagada = TRUE WHERE id = %s", (cuota_id,))
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Cuota pagada", "descontado": importe, "fondo_restante": acumulado - importe}

@router.delete("/cuotas/{cuota_id}")
def eliminar_cuota(cuota_id: int, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM cuotas_periodicas WHERE id = %s", (cuota_id,))
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Cuota eliminada"}