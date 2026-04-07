from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from database import get_connection
from auth import decode_token
from pydantic import BaseModel
from typing import Optional
import datetime

router = APIRouter(prefix="/fondo-periodicos", tags=["fondo-periodicos"])
security = HTTPBearer()

class CuotaRequest(BaseModel):
    gasto_periodico_id: int
    importe: float
    fecha_pago: str

class PagarCuotaRequest(BaseModel):
    cuota_id: int

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
def get_fondo(user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)
    hoy = datetime.date.today()

    # Acumulado total del fondo
    cur.execute("""
        SELECT COALESCE(SUM(acumulado), 0)
        FROM fondo_periodicos WHERE hogar_id = %s
    """, (hogar_id,))
    acumulado_total = float(cur.fetchone()[0])

    # Reserva mensual total de todos los periódicos
    cur.execute("""
        SELECT COALESCE(SUM(reserva_mensual), 0)
        FROM gastos_periodicos WHERE hogar_id = %s
    """, (hogar_id,))
    reserva_mensual = float(cur.fetchone()[0])

    # Próximas cuotas pendientes
    cur.execute("""
        SELECT cp.id, gp.nombre, cp.importe, cp.fecha_pago, cp.pagada,
               (cp.fecha_pago - CURRENT_DATE) as dias_restantes
        FROM cuotas_periodicas cp
        JOIN gastos_periodicos gp ON cp.gasto_periodico_id = gp.id
        WHERE gp.hogar_id = %s AND cp.pagada = FALSE
        ORDER BY cp.fecha_pago ASC
    """, (hogar_id,))
    cuotas = cur.fetchall()

    cur.close()
    conn.close()

    return {
        "acumulado": acumulado_total,
        "reserva_mensual": reserva_mensual,
        "cuotas_pendientes": [{
            "id": r[0],
            "nombre": r[1],
            "importe": float(r[2]),
            "fecha_pago": str(r[3]),
            "pagada": r[4],
            "dias_restantes": r[5].days if r[5] else None,
            "alerta": r[5].days <= 30 if r[5] else False,
            "cubierta": acumulado_total >= float(r[2])
        } for r in cuotas]
    }

@router.post("/acumular")
def acumular_mes(user_id: int = Depends(get_user)):
    mes = datetime.date.today().month
    anio = datetime.date.today().year
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)

    # Calcular reserva mensual total
    cur.execute("""
        SELECT COALESCE(SUM(reserva_mensual), 0)
        FROM gastos_periodicos WHERE hogar_id = %s
    """, (hogar_id,))
    reserva = float(cur.fetchone()[0])

    # Comprobar si ya se acumuló este mes
    cur.execute("""
        SELECT id FROM fondo_periodicos
        WHERE hogar_id = %s AND mes = %s AND anio = %s
    """, (hogar_id, mes, anio))
    existente = cur.fetchone()

    if existente:
        raise HTTPException(status_code=400, detail="Ya se acumuló este mes")

    cur.execute("""
        INSERT INTO fondo_periodicos (hogar_id, acumulado, mes, anio)
        VALUES (%s, %s, %s, %s)
    """, (hogar_id, reserva, mes, anio))
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Reserva acumulada", "cantidad": reserva}

@router.post("/cuotas")
def crear_cuota(data: CuotaRequest, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)

    # Verificar que el gasto periódico pertenece al hogar
    cur.execute("""
        SELECT id FROM gastos_periodicos
        WHERE id = %s AND hogar_id = %s
    """, (data.gasto_periodico_id, hogar_id))
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail="Gasto periódico no encontrado")

    cur.execute("""
        INSERT INTO cuotas_periodicas (gasto_periodico_id, importe, fecha_pago)
        VALUES (%s, %s, %s) RETURNING id
    """, (data.gasto_periodico_id, data.importe, data.fecha_pago))
    cuota_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Cuota creada", "id": cuota_id}

@router.put("/cuotas/{cuota_id}/pagar")
def pagar_cuota(cuota_id: int, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)

    # Obtener importe de la cuota
    cur.execute("""
        SELECT cp.importe FROM cuotas_periodicas cp
        JOIN gastos_periodicos gp ON cp.gasto_periodico_id = gp.id
        WHERE cp.id = %s AND gp.hogar_id = %s AND cp.pagada = FALSE
    """, (cuota_id, hogar_id))
    cuota = cur.fetchone()
    if not cuota:
        raise HTTPException(status_code=404, detail="Cuota no encontrada")

    importe = float(cuota[0])

    # Verificar que hay suficiente en el fondo
    cur.execute("""
        SELECT COALESCE(SUM(acumulado), 0)
        FROM fondo_periodicos WHERE hogar_id = %s
    """, (hogar_id,))
    acumulado = float(cur.fetchone()[0])

    if acumulado < importe:
        raise HTTPException(
            status_code=400,
            detail=f"Fondo insuficiente. Acumulado: {acumulado:.2f}€, necesitas: {importe:.2f}€"
        )

    # Descontar del fondo y marcar como pagada
    cur.execute("""
        UPDATE fondo_periodicos
        SET acumulado = acumulado - %s
        WHERE hogar_id = %s AND id = (
            SELECT id FROM fondo_periodicos
            WHERE hogar_id = %s ORDER BY creado_en DESC LIMIT 1
        )
    """, (importe, hogar_id, hogar_id))

    cur.execute("""
        UPDATE cuotas_periodicas SET pagada = TRUE WHERE id = %s
    """, (cuota_id,))

    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Cuota pagada", "descontado": importe, "fondo_restante": acumulado - importe}

@router.delete("/cuotas/{cuota_id}")
def eliminar_cuota(cuota_id: int, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)
    cur.execute("""
        DELETE FROM cuotas_periodicas cp
        USING gastos_periodicos gp
        WHERE cp.gasto_periodico_id = gp.id
        AND cp.id = %s AND gp.hogar_id = %s
    """, (cuota_id, hogar_id))
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Cuota eliminada"}