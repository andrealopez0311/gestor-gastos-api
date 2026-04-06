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
    total = data.porcentaje_ahorro + data.porcentaje_comunes + data.porcentaje_personal
    if abs(total - 100.0) > 0.01:
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
    cur.execute("""
        SELECT COALESCE(SUM(importe), 0)
        FROM ingresos
        WHERE hogar_id = %s AND mes = %s AND anio = %s
    """, (hogar_id, mes, anio))
    ingreso_total = float(cur.fetchone()[0])
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
    monto_ahorro = ingreso_total * pct_ahorro / 100
    monto_comunes = ingreso_total * pct_comunes / 100
    monto_personal = ingreso_total * pct_personal / 100
    cur.execute("""
        SELECT COALESCE(SUM(importe), 0)
        FROM gastos_comunes
        WHERE hogar_id = %s
        AND DATE_TRUNC('month', fecha) = DATE_TRUNC('month', CURRENT_DATE)
    """, (hogar_id,))
    gastos_comunes_real = float(cur.fetchone()[0])
    cur.execute("""
        SELECT COALESCE(SUM(importe), 0)
        FROM gastos
        WHERE usuario_id = %s
        AND DATE_TRUNC('month', fecha) = DATE_TRUNC('month', CURRENT_DATE)
    """, (user_id,))
    gastos_personales_real = float(cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM hogar_miembros WHERE hogar_id = %s", (hogar_id,))
    num_miembros = cur.fetchone()[0]
    personal_por_miembro = monto_personal / num_miembros if num_miembros > 0 else 0
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
            "comunes": monto_comunes,
            "personal_total": monto_personal,
            "personal_por_miembro": personal_por_miembro
        },
        "real": {
            "gastos_comunes": gastos_comunes_real,
            "gastos_personales": gastos_personales_real,
            "disponible_comunes": monto_comunes - gastos_comunes_real,
            "disponible_personal": personal_por_miembro - gastos_personales_real
        }
    }