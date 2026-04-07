from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from database import get_connection
from auth import decode_token
from pydantic import BaseModel
import datetime

router = APIRouter(prefix="/presupuesto", tags=["presupuesto"])
security = HTTPBearer()

class PresupuestoRequest(BaseModel):
    porcentaje_ahorro: float
    porcentaje_comunes: float
    porcentaje_personal: float

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
def crear_presupuesto(data: PresupuestoRequest, user_id: int = Depends(get_user)):
    if abs(data.porcentaje_ahorro + data.porcentaje_comunes + data.porcentaje_personal - 100.0) > 0.01:
        raise HTTPException(status_code=400, detail="Los porcentajes deben sumar 100")
    mes = datetime.date.today().month
    anio = datetime.date.today().year
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)
    cur.execute("""
        SELECT id FROM presupuesto_hogar
        WHERE hogar_id = %s AND mes = %s AND anio = %s
    """, (hogar_id, mes, anio))
    existente = cur.fetchone()
    if existente:
        cur.execute("""
            UPDATE presupuesto_hogar
            SET porcentaje_ahorro = %s, porcentaje_comunes = %s, porcentaje_personal = %s
            WHERE id = %s
        """, (data.porcentaje_ahorro, data.porcentaje_comunes, data.porcentaje_personal, existente[0]))
        mensaje = "Presupuesto actualizado"
    else:
        cur.execute("""
            INSERT INTO presupuesto_hogar (hogar_id, mes, anio, porcentaje_ahorro, porcentaje_comunes, porcentaje_personal)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (hogar_id, mes, anio, data.porcentaje_ahorro, data.porcentaje_comunes, data.porcentaje_personal))
        mensaje = "Presupuesto creado"
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": mensaje}

@router.get("/")
def get_presupuesto(user_id: int = Depends(get_user)):
    mes = datetime.date.today().month
    anio = datetime.date.today().year
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)
    cur.execute("""
        SELECT porcentaje_ahorro, porcentaje_comunes, porcentaje_personal
        FROM presupuesto_hogar
        WHERE hogar_id = %s AND mes = %s AND anio = %s
    """, (hogar_id, mes, anio))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return {"porcentaje_ahorro": 20.0, "porcentaje_comunes": 50.0, "porcentaje_personal": 30.0}
    return {"porcentaje_ahorro": float(row[0]), "porcentaje_comunes": float(row[1]), "porcentaje_personal": float(row[2])}

@router.get("/resumen")
def get_resumen_hogar(user_id: int = Depends(get_user)):
    mes = datetime.date.today().month
    anio = datetime.date.today().year
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)

    # Ingresos totales del hogar
    cur.execute("""
        SELECT COALESCE(SUM(importe), 0)
        FROM ingresos
        WHERE hogar_id = %s AND mes = %s AND anio = %s
    """, (hogar_id, mes, anio))
    ingreso_total = float(cur.fetchone()[0])

    # Presupuesto del hogar
    cur.execute("""
        SELECT porcentaje_ahorro
        FROM presupuesto_hogar
        WHERE hogar_id = %s AND mes = %s AND anio = %s
    """, (hogar_id, mes, anio))
    presupuesto = cur.fetchone()
    pct_ahorro = float(presupuesto[0]) if presupuesto else 20.0

    # Calcular ahorro
    monto_ahorro = ingreso_total * pct_ahorro / 100
    tras_ahorro = ingreso_total - monto_ahorro

    # Total gastos comunes reales del mes
    cur.execute("""
        SELECT COALESCE(SUM(importe), 0)
        FROM gastos_comunes
        WHERE hogar_id = %s
        AND DATE_TRUNC('month', fecha) = DATE_TRUNC('month', CURRENT_DATE)
    """, (hogar_id,))
    gastos_comunes_real = float(cur.fetchone()[0])

    # Total reserva periódicos
    cur.execute("""
        SELECT COALESCE(SUM(reserva_mensual), 0)
        FROM gastos_periodicos
        WHERE hogar_id = %s
    """, (hogar_id,))
    total_periodicos = float(cur.fetchone()[0])

    # Total egresos = gastos comunes + periódicos
    total_egresos = gastos_comunes_real + total_periodicos

    # Disponible para mesada
    disponible_mesada = tras_ahorro - total_egresos

    # Número de miembros
    cur.execute("SELECT COUNT(*) FROM hogar_miembros WHERE hogar_id = %s", (hogar_id,))
    num_miembros = cur.fetchone()[0]
    mesada_por_miembro = disponible_mesada / num_miembros if num_miembros > 0 else disponible_mesada

    # Gastos personales del usuario este mes
    cur.execute("""
        SELECT COALESCE(SUM(importe), 0)
        FROM gastos
        WHERE usuario_id = %s
        AND DATE_TRUNC('month', fecha) = DATE_TRUNC('month', CURRENT_DATE)
    """, (user_id,))
    gastos_personales = float(cur.fetchone()[0])

    # Ahorro personal acumulado
    cur.execute("""
        SELECT COALESCE(SUM(acumulado), 0)
        FROM ahorro_personal
        WHERE usuario_id = %s
    """, (user_id,))
    ahorro_personal = float(cur.fetchone()[0])

    # Ahorro voluntario del mes
    cur.execute("""
        SELECT COALESCE(SUM(cantidad), 0)
        FROM ahorro_voluntario
        WHERE usuario_id = %s AND mes = %s AND anio = %s
    """, (user_id, mes, anio))
    ahorro_voluntario = float(cur.fetchone()[0])

    # Total descontado de la mesada
    total_descontado_mesada = gastos_personales + ahorro_personal + ahorro_voluntario
    disponible_personal = mesada_por_miembro - total_descontado_mesada

    # Ahorro acumulado en fondos familiares
    cur.execute("""
        SELECT COALESCE(SUM(acumulado), 0)
        FROM ahorro
        WHERE hogar_id = %s
    """, (hogar_id,))
    ahorro_acumulado = float(cur.fetchone()[0])

    cur.close()
    conn.close()

    return {
        "ingreso_total": ingreso_total,
        "num_miembros": num_miembros,
        "presupuesto": {
            "pct_ahorro": pct_ahorro
        },
        "montos": {
            "ahorro": monto_ahorro,
            "tras_ahorro": tras_ahorro,
            "egresos": total_egresos,
            "gastos_comunes": gastos_comunes_real,
            "periodicos": total_periodicos,
            "mesada_total": disponible_mesada,
            "mesada_por_miembro": mesada_por_miembro
        },
        "personal": {
            "mesada": mesada_por_miembro,
            "gastado": gastos_personales,
            "ahorro_personal": ahorro_personal,
            "ahorro_voluntario": ahorro_voluntario,
            "total_descontado": total_descontado_mesada,
            "disponible": disponible_personal
        },
        "ahorro_acumulado": ahorro_acumulado
    }