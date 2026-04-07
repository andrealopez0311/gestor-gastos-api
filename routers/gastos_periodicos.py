from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from database import get_connection
from auth import decode_token
from pydantic import BaseModel
from typing import Optional
import datetime

router = APIRouter(prefix="/gastos-periodicos", tags=["gastos-periodicos"])
security = HTTPBearer()

class GastoPeriodicoRequest(BaseModel):
    nombre: str
    importe: float
    frecuencia: int
    proximo_pago: Optional[str] = None

class EditarGastoPeriodicoRequest(BaseModel):
    nombre: Optional[str] = None
    importe: Optional[float] = None
    frecuencia: Optional[int] = None
    proximo_pago: Optional[str] = None

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

@router.get("/")
def get_gastos_periodicos(user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id_opcional(cur, user_id)

    if hogar_id:
        cur.execute("""
            SELECT id, nombre, importe, frecuencia, reserva_mensual,
                   proximo_pago, acumulado
            FROM gastos_periodicos
            WHERE hogar_id = %s
            ORDER BY proximo_pago ASC NULLS LAST
        """, (hogar_id,))
    else:
        cur.execute("""
            SELECT id, nombre, importe, frecuencia, reserva_mensual,
                   proximo_pago, acumulado
            FROM gastos_periodicos
            WHERE usuario_id = %s AND hogar_id IS NULL
            ORDER BY proximo_pago ASC NULLS LAST
        """, (user_id,))

    rows = cur.fetchall()
    total_reserva = sum(float(r[4]) for r in rows)
    hoy = datetime.date.today()
    resultado = []
    for r in rows:
        proximo = r[5]
        dias_restantes = None
        alerta = False
        if proximo:
            dias_restantes = (proximo - hoy).days
            alerta = dias_restantes <= 30
        resultado.append({
            "id": r[0],
            "nombre": r[1],
            "importe": float(r[2]),
            "frecuencia": r[3],
            "reserva_mensual": float(r[4]),
            "proximo_pago": str(proximo) if proximo else None,
            "acumulado": float(r[6]),
            "dias_restantes": dias_restantes,
            "alerta": alerta,
            "listo": float(r[6]) >= float(r[2])
        })

    cur.close()
    conn.close()
    return {"total_reserva_mensual": total_reserva, "gastos": resultado}

@router.post("/")
def crear_gasto_periodico(data: GastoPeriodicoRequest, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id_opcional(cur, user_id)
    cur.execute("""
        INSERT INTO gastos_periodicos (hogar_id, usuario_id, nombre, importe, frecuencia, proximo_pago)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, reserva_mensual
    """, (hogar_id, user_id, data.nombre, data.importe, data.frecuencia, data.proximo_pago))
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Gasto periódico creado", "id": row[0], "reserva_mensual": float(row[1])}

@router.put("/{gasto_id}")
def editar_gasto_periodico(gasto_id: int, data: EditarGastoPeriodicoRequest, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id_opcional(cur, user_id)

    if hogar_id:
        cur.execute("""
            SELECT nombre, importe, frecuencia, proximo_pago
            FROM gastos_periodicos WHERE id = %s AND hogar_id = %s
        """, (gasto_id, hogar_id))
    else:
        cur.execute("""
            SELECT nombre, importe, frecuencia, proximo_pago
            FROM gastos_periodicos WHERE id = %s AND usuario_id = %s AND hogar_id IS NULL
        """, (gasto_id, user_id))

    actual = cur.fetchone()
    if not actual:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")

    nombre = data.nombre if data.nombre is not None else actual[0]
    importe = data.importe if data.importe is not None else float(actual[1])
    frecuencia = data.frecuencia if data.frecuencia is not None else actual[2]
    proximo_pago = data.proximo_pago if data.proximo_pago is not None else str(actual[3]) if actual[3] else None

    if hogar_id:
        cur.execute("""
            UPDATE gastos_periodicos
            SET nombre = %s, importe = %s, frecuencia = %s, proximo_pago = %s
            WHERE id = %s AND hogar_id = %s
        """, (nombre, importe, frecuencia, proximo_pago, gasto_id, hogar_id))
    else:
        cur.execute("""
            UPDATE gastos_periodicos
            SET nombre = %s, importe = %s, frecuencia = %s, proximo_pago = %s
            WHERE id = %s AND usuario_id = %s AND hogar_id IS NULL
        """, (nombre, importe, frecuencia, proximo_pago, gasto_id, user_id))

    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Gasto periódico actualizado"}

@router.delete("/{gasto_id}")
def eliminar_gasto_periodico(gasto_id: int, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id_opcional(cur, user_id)
    if hogar_id:
        cur.execute("DELETE FROM gastos_periodicos WHERE id = %s AND hogar_id = %s", (gasto_id, hogar_id))
    else:
        cur.execute("DELETE FROM gastos_periodicos WHERE id = %s AND usuario_id = %s AND hogar_id IS NULL", (gasto_id, user_id))
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Gasto periódico eliminado"}

@router.post("/{gasto_id}/pagar")
def registrar_pago(gasto_id: int, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id_opcional(cur, user_id)

    if hogar_id:
        cur.execute("""
            SELECT importe FROM gastos_periodicos
            WHERE id = %s AND hogar_id = %s
        """, (gasto_id, hogar_id))
    else:
        cur.execute("""
            SELECT importe FROM gastos_periodicos
            WHERE id = %s AND usuario_id = %s AND hogar_id IS NULL
        """, (gasto_id, user_id))

    gasto = cur.fetchone()
    if not gasto:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    importe = float(gasto[0])

    # Calcular acumulado teórico del fondo
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

    if hogar_id:
        cur.execute("SELECT MIN(creado_en) FROM gastos_periodicos WHERE hogar_id = %s", (hogar_id,))
    else:
        cur.execute("SELECT MIN(creado_en) FROM gastos_periodicos WHERE usuario_id = %s AND hogar_id IS NULL", (user_id,))
    primera_fecha = cur.fetchone()[0]

    hoy = datetime.date.today()
    meses = (hoy.year - primera_fecha.year) * 12 + (hoy.month - primera_fecha.month) + 1 if primera_fecha else 1
    acumulado_teorico = reserva_mensual * meses

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
    acumulado_disponible = acumulado_teorico - total_pagado

    if acumulado_disponible < importe:
        raise HTTPException(
            status_code=400,
            detail=f"Fondo insuficiente. Disponible: {acumulado_disponible:.2f}€, necesitas: {importe:.2f}€"
        )

    cur.execute("""
        INSERT INTO cuotas_periodicas (gasto_periodico_id, importe, fecha_pago, pagada)
        VALUES (%s, %s, CURRENT_DATE, TRUE)
    """, (gasto_id, importe))

    cur.execute("""
        UPDATE gastos_periodicos
        SET proximo_pago = CASE
            WHEN proximo_pago IS NOT NULL
            THEN proximo_pago + (frecuencia * INTERVAL '1 month')
            ELSE CURRENT_DATE + (frecuencia * INTERVAL '1 month')
        END
        WHERE id = %s
    """, (gasto_id,))

    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Pago registrado", "descontado": importe, "fondo_restante": acumulado_disponible - importe}