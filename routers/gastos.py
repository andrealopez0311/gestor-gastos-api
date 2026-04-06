from fastapi import APIRouter, Header, HTTPException
from database import get_connection
from auth import decode_token
from pydantic import BaseModel
from typing import Optional
import datetime

router = APIRouter(prefix="/gastos", tags=["gastos"])

class GastoRequest(BaseModel):
    categoria_id: int
    descripcion: Optional[str] = ""
    importe: float
    fecha: Optional[str] = None

def get_user(authorization: str):
    token = authorization.replace("Bearer ", "")
    user_id = decode_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="No autorizado")
    return int(user_id)

@router.get("/")
def get_gastos(authorization: str = Header(...)):
    user_id = get_user(authorization)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT g.id, c.nombre, g.descripcion, g.importe, g.fecha
        FROM gastos g
        JOIN categorias c ON g.categoria_id = c.id
        WHERE g.usuario_id = %s
        ORDER BY g.fecha DESC
        LIMIT 50
    """, (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"id": r[0], "categoria": r[1], "descripcion": r[2], "importe": float(r[3]), "fecha": str(r[4])} for r in rows]

@router.post("/")
def crear_gasto(data: GastoRequest, authorization: str = Header(...)):
    user_id = get_user(authorization)
    fecha = data.fecha or str(datetime.date.today())
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO gastos (usuario_id, categoria_id, descripcion, importe, fecha) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (user_id, data.categoria_id, data.descripcion, data.importe, fecha)
    )
    gasto_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Gasto creado", "id": gasto_id}

@router.delete("/{gasto_id}")
def eliminar_gasto(gasto_id: int, authorization: str = Header(...)):
    user_id = get_user(authorization)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM gastos WHERE id = %s AND usuario_id = %s", (gasto_id, user_id))
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Gasto eliminado"}

@router.get("/resumen")
def resumen_mensual(authorization: str = Header(...)):
    user_id = get_user(authorization)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT c.nombre, c.color, SUM(g.importe) as total
        FROM gastos g
        JOIN categorias c ON g.categoria_id = c.id
        WHERE g.usuario_id = %s
        AND DATE_TRUNC('month', g.fecha) = DATE_TRUNC('month', CURRENT_DATE)
        GROUP BY c.nombre, c.color
        ORDER BY total DESC
    """, (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"categoria": r[0], "color": r[1], "total": float(r[2])} for r in rows]