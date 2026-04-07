from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from database import get_connection
from auth import decode_token
from pydantic import BaseModel
from typing import Optional
import datetime

router = APIRouter(prefix="/gastos-comunes", tags=["gastos-comunes"])
security = HTTPBearer()

class GastoComunRequest(BaseModel):
    categoria_id: int
    descripcion: Optional[str] = ""
    importe: float
    fecha: Optional[str] = None

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
def get_gastos_comunes(user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)
    cur.execute("""
        SELECT gc.id, c.nombre, gc.descripcion, gc.importe, gc.fecha, u.nombre
        FROM gastos_comunes gc
        JOIN categorias c ON gc.categoria_id = c.id
        JOIN usuarios u ON gc.usuario_id = u.id
        WHERE gc.hogar_id = %s
        AND DATE_TRUNC('month', gc.fecha) = DATE_TRUNC('month', CURRENT_DATE)
        ORDER BY gc.fecha DESC
    """, (hogar_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"id": r[0], "categoria": r[1], "descripcion": r[2], "importe": float(r[3]), "fecha": str(r[4]), "añadido_por": r[5]} for r in rows]

@router.post("/")
def crear_gasto_comun(data: GastoComunRequest, user_id: int = Depends(get_user)):
    fecha = data.fecha or str(datetime.date.today())
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)
    cur.execute("""
        INSERT INTO gastos_comunes (hogar_id, usuario_id, categoria_id, descripcion, importe, fecha)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
    """, (hogar_id, user_id, data.categoria_id, data.descripcion, data.importe, fecha))
    gasto_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Gasto común añadido", "id": gasto_id}

@router.delete("/{gasto_id}")
def eliminar_gasto_comun(gasto_id: int, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)
    cur.execute("""
        DELETE FROM gastos_comunes
        WHERE id = %s AND hogar_id = %s
    """, (gasto_id, hogar_id))
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Gasto común eliminado"}

@router.get("/resumen")
def resumen_gastos_comunes(user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)
    cur.execute("""
        SELECT c.nombre, c.color, SUM(gc.importe) as total
        FROM gastos_comunes gc
        JOIN categorias c ON gc.categoria_id = c.id
        WHERE gc.hogar_id = %s
        AND DATE_TRUNC('month', gc.fecha) = DATE_TRUNC('month', CURRENT_DATE)
        GROUP BY c.nombre, c.color
        ORDER BY total DESC
    """, (hogar_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"categoria": r[0], "color": r[1], "total": float(r[2])} for r in rows]

class EditarGastoComunRequest(BaseModel):
    descripcion: Optional[str] = None
    importe: Optional[float] = None
    fecha: Optional[str] = None
    categoria_id: Optional[int] = None

@router.put("/{gasto_id}")
def editar_gasto_comun(gasto_id: int, data: EditarGastoComunRequest, user_id: int = Depends(get_user)):
    conn = get_connection()
    cur = conn.cursor()
    hogar_id = get_hogar_id(cur, user_id)

    # Obtener gasto actual
    cur.execute("""
        SELECT descripcion, importe, fecha, categoria_id
        FROM gastos_comunes WHERE id = %s AND hogar_id = %s
    """, (gasto_id, hogar_id))
    actual = cur.fetchone()
    if not actual:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")

    # Usar valores actuales si no se mandan nuevos
    descripcion = data.descripcion if data.descripcion is not None else actual[0]
    importe = data.importe if data.importe is not None else float(actual[1])
    fecha = data.fecha if data.fecha is not None else str(actual[2])
    categoria_id = data.categoria_id if data.categoria_id is not None else actual[3]

    cur.execute("""
        UPDATE gastos_comunes
        SET descripcion = %s, importe = %s, fecha = %s, categoria_id = %s
        WHERE id = %s AND hogar_id = %s
    """, (descripcion, importe, fecha, categoria_id, gasto_id, hogar_id))
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Gasto común actualizado"}