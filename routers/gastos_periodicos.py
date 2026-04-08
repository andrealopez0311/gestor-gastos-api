from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from database import get_connection
from auth import decode_token
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import datetime

router = APIRouter(prefix="/gastos-periodicos", tags=["gastos-periodicos"])
security = HTTPBearer()

class GastoPeriodicoRequest(BaseModel):
    nombre: str
    importe: float
    frecuencia: int
    proximo_pago: Optional[str] = None
    cuotas: Optional[List[Dict[str, Any]]] = None

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
    gasto_id = row[0]
    reserva = float(row[1])

    # Crear cuotas irregulares si se proporcionan
    if data.cuotas:
        for cuota in data.cuotas:
            cur.execute("""
                INSERT INTO cuotas_periodicas (gasto_periodico_id, importe, fecha_pago)
                VALUES (%s, %s, %s)
            """, (gasto_id, cuota["importe"], cuota["fecha_pago"]))

    conn.commit()
    cur.close()
    conn.close()
    return {
        "mensaje": "Gasto periódico creado",
        "id": gasto_id,
        "reserva_mensual": reserva
    }

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
            SELECT importe, frecuencia, proximo_pago
            FROM gastos_periodicos WHERE id = %s AND hogar_id = %s
        """, (gasto_id, hogar_id))
    else:
        cur.execute("""
            SELECT importe, frecuencia, proximo_pago
            FROM gastos_periodicos WHERE id = %s AND usuario_id = %s AND hogar_id IS NULL
        """, (gasto_id, user_id))

    gasto = cur.fetchone()
    if not gasto:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")

    importe = float(gasto[0])
    frecuencia = gasto[1]
    proximo_pago = gasto[2]

    # Verificar si tiene cuotas irregulares pendientes
    cur.execute("""
        SELECT id, importe, fecha_pago FROM cuotas_periodicas
        WHERE gasto_periodico_id = %s AND pagada = FALSE
        ORDER BY fecha_pago ASC LIMIT 1
    """, (gasto_id,))
    cuota_proxima = cur.fetchone()

    # Saldo real del fondo
    cur.execute("""
        SELECT COALESCE(SUM(acumulado), 0)
        FROM fondo_periodicos
        WHERE hogar_id IS NOT DISTINCT FROM %s
    """, (hogar_id,))
    saldo_fondo = float(cur.fetchone()[0])

    # Total ya pagado en cuotas
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
    acumulado_disponible = saldo_fondo - total_pagado

    hoy = datetime.date.today()

    if cuota_proxima:
        cuota_id = cuota_proxima[0]
        importe_cuota = float(cuota_proxima[1])
        fecha_cuota = cuota_proxima[2]

        if acumulado_disponible < importe_cuota:
            raise HTTPException(
                status_code=400,
                detail=f"Fondo insuficiente. Disponible: {acumulado_disponible:.2f}€, necesitas: {importe_cuota:.2f}€"
            )

        cur.execute("UPDATE cuotas_periodicas SET pagada = TRUE WHERE id = %s", (cuota_id,))

        nueva_fecha = fecha_cuota.replace(year=fecha_cuota.year + 1)
        cur.execute("""
            INSERT INTO cuotas_periodicas (gasto_periodico_id, importe, fecha_pago)
            VALUES (%s, %s, %s)
        """, (gasto_id, importe_cuota, nueva_fecha))

        cur.execute("""
            SELECT fecha_pago FROM cuotas_periodicas
            WHERE gasto_periodico_id = %s AND pagada = FALSE
            ORDER BY fecha_pago ASC LIMIT 1
        """, (gasto_id,))
        siguiente = cur.fetchone()
        if siguiente:
            cur.execute("UPDATE gastos_periodicos SET proximo_pago = %s WHERE id = %s",
                       (siguiente[0], gasto_id))

        importe_pagado = importe_cuota

    else:
        if acumulado_disponible < importe:
            raise HTTPException(
                status_code=400,
                detail=f"Fondo insuficiente. Disponible: {acumulado_disponible:.2f}€, necesitas: {importe:.2f}€"
            )

        cur.execute("""
            INSERT INTO cuotas_periodicas (gasto_periodico_id, importe, fecha_pago, pagada)
            VALUES (%s, %s, CURRENT_DATE, TRUE)
        """, (gasto_id, importe))

        if proximo_pago:
            nuevo_proximo = proximo_pago + datetime.timedelta(days=frecuencia * 30)
        else:
            nuevo_proximo = hoy + datetime.timedelta(days=frecuencia * 30)

        cur.execute("UPDATE gastos_periodicos SET proximo_pago = %s WHERE id = %s",
                   (nuevo_proximo, gasto_id))

        importe_pagado = importe

    # Descontar del fondo real
    cur.execute("""
        UPDATE fondo_periodicos
        SET acumulado = GREATEST(0, acumulado - %s)
        WHERE hogar_id IS NOT DISTINCT FROM %s
        AND id = (
            SELECT id FROM fondo_periodicos
            WHERE hogar_id IS NOT DISTINCT FROM %s
            ORDER BY creado_en DESC LIMIT 1
        )
    """, (importe_pagado, hogar_id, hogar_id))

    conn.commit()
    cur.close()
    conn.close()
    return {
        "mensaje": "Pago registrado",
        "descontado": importe_pagado,
        "fondo_restante": acumulado_disponible - importe_pagado
    }

@router.get("/{gasto_id}/cuotas")
def get_cuotas(gasto_id: int, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id_opcional(cur, user_id)

    # Verificar que el gasto pertenece al usuario o su hogar
    if hogar_id:
        cur.execute("""
            SELECT id FROM gastos_periodicos
            WHERE id = %s AND hogar_id = %s
        """, (gasto_id, hogar_id))
    else:
        cur.execute("""
            SELECT id FROM gastos_periodicos
            WHERE id = %s AND usuario_id = %s AND hogar_id IS NULL
        """, (gasto_id, user_id))

    if not cur.fetchone():
        raise HTTPException(status_code=404, detail="Gasto no encontrado")

    cur.execute("""
        SELECT id, importe, fecha_pago, pagada
        FROM cuotas_periodicas
        WHERE gasto_periodico_id = %s
        ORDER BY fecha_pago ASC
    """, (gasto_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    hoy = datetime.date.today()
    return [{
        "id": r[0],
        "importe": float(r[1]),
        "fecha_pago": str(r[2]),
        "pagada": r[3],
        "dias_restantes": (r[2] - hoy).days if r[2] else None,
        "alerta": (r[2] - hoy).days <= 30 if r[2] else False
    } for r in rows]