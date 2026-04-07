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
def get_gastos_periodicos(user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)
    cur.execute("""
        SELECT id, nombre, importe, frecuencia, reserva_mensual,
               proximo_pago, acumulado
        FROM gastos_periodicos
        WHERE hogar_id = %s
        ORDER BY proximo_pago ASC NULLS LAST
    """, (hogar_id,))
    rows = cur.fetchall()

    # Calcular total reserva mensual
    total_reserva = sum(float(r[4]) for r in rows)

    # Calcular alertas de próximo pago
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
    return {
        "total_reserva_mensual": total_reserva,
        "gastos": resultado
    }

@router.post("/")
def crear_gasto_periodico(data: GastoPeriodicoRequest, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)
    cur.execute("""
        INSERT INTO gastos_periodicos (hogar_id, nombre, importe, frecuencia, proximo_pago)
        VALUES (%s, %s, %s, %s, %s) RETURNING id, reserva_mensual
    """, (hogar_id, data.nombre, data.importe, data.frecuencia, data.proximo_pago))
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return {
        "mensaje": "Gasto periódico creado",
        "id": row[0],
        "reserva_mensual": float(row[1])
    }

@router.put("/{gasto_id}/acumular")
def acumular_reserva(gasto_id: int, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)
    cur.execute("""
        UPDATE gastos_periodicos
        SET acumulado = acumulado + reserva_mensual
        WHERE id = %s AND hogar_id = %s
        RETURNING acumulado, importe
    """, (gasto_id, hogar_id))
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    return {
        "mensaje": "Reserva acumulada",
        "acumulado": float(row[0]),
        "listo": float(row[0]) >= float(row[1])
    }

@router.post("/{gasto_id}/pagar")
def registrar_pago(gasto_id: int, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT hogar_id FROM hogar_miembros WHERE usuario_id = %s", (user_id,))
    hogar = cur.fetchone()
    if not hogar:
        raise HTTPException(status_code=400, detail="No perteneces a ningún hogar")
    hogar_id = hogar[0]

    # Obtener importe del gasto periódico
    cur.execute("""
        SELECT importe, nombre FROM gastos_periodicos
        WHERE id = %s AND hogar_id = %s
    """, (gasto_id, hogar_id))
    gasto = cur.fetchone()
    if not gasto:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    importe = float(gasto[0])

    # Calcular acumulado teórico del fondo
    cur.execute("""
        SELECT COALESCE(SUM(reserva_mensual), 0)
        FROM gastos_periodicos WHERE hogar_id = %s
    """, (hogar_id,))
    reserva_mensual = float(cur.fetchone()[0])

    cur.execute("""
        SELECT MIN(creado_en) FROM gastos_periodicos WHERE hogar_id = %s
    """, (hogar_id,))
    primera_fecha = cur.fetchone()[0]

    import datetime
    hoy = datetime.date.today()
    if primera_fecha:
        meses = (hoy.year - primera_fecha.year) * 12 + (hoy.month - primera_fecha.month) + 1
    else:
        meses = 1

    acumulado_teorico = reserva_mensual * meses

    # Total ya pagado en cuotas
    cur.execute("""
        SELECT COALESCE(SUM(cp.importe), 0)
        FROM cuotas_periodicas cp
        JOIN gastos_periodicos gp ON cp.gasto_periodico_id = gp.id
        WHERE gp.hogar_id = %s AND cp.pagada = TRUE
    """, (hogar_id,))
    total_pagado_cuotas = float(cur.fetchone()[0])

    acumulado_disponible = acumulado_teorico - total_pagado_cuotas

    if acumulado_disponible < importe:
        raise HTTPException(
            status_code=400,
            detail=f"Fondo insuficiente. Disponible: {acumulado_disponible:.2f}€, necesitas: {importe:.2f}€"
        )

    # Registrar el pago como cuota pagada
    cur.execute("""
        INSERT INTO cuotas_periodicas (gasto_periodico_id, importe, fecha_pago, pagada)
        VALUES (%s, %s, CURRENT_DATE, TRUE)
    """, (gasto_id, importe))

    # Actualizar próximo pago
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
    return {
        "mensaje": "Pago registrado",
        "descontado": importe,
        "fondo_restante": acumulado_disponible - importe
    }

@router.delete("/{gasto_id}")
def eliminar_gasto_periodico(gasto_id: int, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)
    cur.execute("""
        DELETE FROM gastos_periodicos
        WHERE id = %s AND hogar_id = %s
    """, (gasto_id, hogar_id))
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Gasto periódico eliminado"}

@router.get("/resumen-presupuesto")
def resumen_con_periodicos(user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)
    mes = datetime.date.today().month
    anio = datetime.date.today().year

    # Ingresos totales
    cur.execute("""
        SELECT COALESCE(SUM(importe), 0)
        FROM ingresos
        WHERE hogar_id = %s AND mes = %s AND anio = %s
    """, (hogar_id, mes, anio))
    ingreso_total = float(cur.fetchone()[0])

    # Presupuesto
    cur.execute("""
        SELECT porcentaje_ahorro, porcentaje_comunes, porcentaje_personal
        FROM presupuesto_hogar
        WHERE hogar_id = %s AND mes = %s AND anio = %s
    """, (hogar_id, mes, anio))
    presupuesto = cur.fetchone()
    if presupuesto:
        pct_ahorro = float(presupuesto[0])
        pct_comunes = float(presupuesto[1])
        pct_personal = float(presupuesto[2])
    else:
        pct_ahorro, pct_comunes, pct_personal = 20.0, 50.0, 30.0

    # Calcular montos
    monto_ahorro = ingreso_total * pct_ahorro / 100
    monto_comunes = ingreso_total * pct_comunes / 100
    monto_personal = ingreso_total * pct_personal / 100

    # Total reserva periódicos
    cur.execute("""
        SELECT COALESCE(SUM(reserva_mensual), 0)
        FROM gastos_periodicos
        WHERE hogar_id = %s
    """, (hogar_id,))
    total_periodicos = float(cur.fetchone()[0])

    # Comunes disponibles tras descontar periódicos
    comunes_disponibles = monto_comunes - total_periodicos

    # Gastos comunes reales del mes
    cur.execute("""
        SELECT COALESCE(SUM(importe), 0)
        FROM gastos_comunes
        WHERE hogar_id = %s
        AND DATE_TRUNC('month', fecha) = DATE_TRUNC('month', CURRENT_DATE)
    """, (hogar_id,))
    gastos_comunes_real = float(cur.fetchone()[0])

    # Gastos personales del usuario
    cur.execute("""
        SELECT COALESCE(SUM(importe), 0)
        FROM gastos
        WHERE usuario_id = %s
        AND DATE_TRUNC('month', fecha) = DATE_TRUNC('month', CURRENT_DATE)
    """, (user_id,))
    gastos_personales_real = float(cur.fetchone()[0])

    # Número de miembros
    cur.execute("SELECT COUNT(*) FROM hogar_miembros WHERE hogar_id = %s", (hogar_id,))
    num_miembros = cur.fetchone()[0]
    personal_por_miembro = monto_personal / num_miembros if num_miembros > 0 else 0

    # Alerta si periódicos superan comunes
    alerta_periodicos = total_periodicos > monto_comunes

    cur.close()
    conn.close()

    return {
        "ingreso_total": ingreso_total,
        "num_miembros": num_miembros,
        "presupuesto": {
            "pct_ahorro": pct_ahorro,
            "pct_comunes": pct_comunes,
            "pct_personal": pct_personal
        },
        "montos": {
            "ahorro": monto_ahorro,
            "comunes_bruto": monto_comunes,
            "periodicos": total_periodicos,
            "comunes_neto": comunes_disponibles,
            "personal_total": monto_personal,
            "personal_por_miembro": personal_por_miembro
        },
        "real": {
            "gastos_comunes": gastos_comunes_real,
            "gastos_personales": gastos_personales_real,
            "disponible_comunes": comunes_disponibles - gastos_comunes_real,
            "disponible_personal": personal_por_miembro - gastos_personales_real
        },
        "alerta_periodicos": alerta_periodicos
    }

class EditarGastoPeriodicoRequest(BaseModel):
    nombre: Optional[str] = None
    importe: Optional[float] = None
    frecuencia: Optional[int] = None
    proximo_pago: Optional[str] = None

@router.put("/{gasto_id}")
def editar_gasto_periodico(gasto_id: int, data: EditarGastoPeriodicoRequest, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)

    cur.execute("""
        SELECT nombre, importe, frecuencia, proximo_pago
        FROM gastos_periodicos WHERE id = %s AND hogar_id = %s
    """, (gasto_id, hogar_id))
    actual = cur.fetchone()
    if not actual:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")

    nombre = data.nombre if data.nombre is not None else actual[0]
    importe = data.importe if data.importe is not None else float(actual[1])
    frecuencia = data.frecuencia if data.frecuencia is not None else actual[2]
    proximo_pago = data.proximo_pago if data.proximo_pago is not None else str(actual[3]) if actual[3] else None

    cur.execute("""
        UPDATE gastos_periodicos
        SET nombre = %s, importe = %s, frecuencia = %s, proximo_pago = %s
        WHERE id = %s AND hogar_id = %s
    """, (nombre, importe, frecuencia, proximo_pago, gasto_id, hogar_id))
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Gasto periódico actualizado"}