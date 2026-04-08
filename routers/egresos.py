from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from database import get_connection
from auth import decode_token
import datetime

router = APIRouter(prefix="/egresos", tags=["egresos"])
security = HTTPBearer()

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
def get_egresos(user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id_opcional(cur, user_id)
    hoy = datetime.date.today()

    # Gastos comunes del mes
    if hogar_id:
        cur.execute("""
            SELECT gc.id, c.nombre, gc.descripcion, gc.importe, gc.fecha,
                   u.nombre as añadido_por
            FROM gastos_comunes gc
            JOIN categorias c ON gc.categoria_id = c.id
            JOIN usuarios u ON gc.usuario_id = u.id
            WHERE gc.hogar_id = %s
            AND DATE_TRUNC('month', gc.fecha) = DATE_TRUNC('month', CURRENT_DATE)
            ORDER BY gc.fecha DESC
        """, (hogar_id,))
    else:
        cur.execute("""
            SELECT gc.id, c.nombre, gc.descripcion, gc.importe, gc.fecha,
                   u.nombre as añadido_por
            FROM gastos_comunes gc
            JOIN categorias c ON gc.categoria_id = c.id
            JOIN usuarios u ON gc.usuario_id = u.id
            WHERE gc.usuario_id = %s AND gc.hogar_id IS NULL
            AND DATE_TRUNC('month', gc.fecha) = DATE_TRUNC('month', CURRENT_DATE)
            ORDER BY gc.fecha DESC
        """, (user_id,))
    gastos_comunes = cur.fetchall()

    # Gastos periódicos
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
    gastos_periodicos = cur.fetchall()

    total_comunes = sum(float(r[3]) for r in gastos_comunes)
    total_periodicos = sum(float(r[4]) for r in gastos_periodicos)
    total_egresos = total_comunes + total_periodicos

    cur.close()
    conn.close()

    return {
        "total_egresos": total_egresos,
        "total_comunes": total_comunes,
        "total_periodicos": total_periodicos,
        "gastos_comunes": [{
            "id": r[0],
            "categoria": r[1],
            "descripcion": r[2],
            "importe": float(r[3]),
            "fecha": str(r[4]),
            "añadido_por": r[5],
            "tipo": "comun"
        } for r in gastos_comunes],
        "gastos_periodicos": [{
            "id": r[0],
            "nombre": r[1],
            "importe": float(r[2]),
            "frecuencia": r[3],
            "reserva_mensual": float(r[4]),
            "proximo_pago": str(r[5]) if r[5] else None,
            "acumulado": float(r[6]),
            "alerta": (r[5] - hoy).days <= 30 if r[5] else False,
            "tipo": "periodico"
        } for r in gastos_periodicos]
    }