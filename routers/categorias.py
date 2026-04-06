from fastapi import APIRouter, Header, HTTPException
from database import get_connection
from auth import decode_token

router = APIRouter(prefix="/categorias", tags=["categorias"])

@router.get("/")
def get_categorias(authorization: str = Header(...)):
    token = authorization.replace("Bearer ", "")
    if not decode_token(token):
        raise HTTPException(status_code=401, detail="No autorizado")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, nombre, icono, color FROM categorias")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"id": r[0], "nombre": r[1], "icono": r[2], "color": r[3]} for r in rows]