from fastapi import FastAPI
from routers import usuarios, gastos, categorias

app = FastAPI(title="Gestor de Gastos API", version="1.0.0")

app.include_router(usuarios.router)
app.include_router(gastos.router)
app.include_router(categorias.router)

@app.get("/")
def root():
    return {"mensaje": "API Gestor de Gastos funcionando ✅"}