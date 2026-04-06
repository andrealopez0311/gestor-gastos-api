from fastapi import FastAPI
from routers import usuarios, gastos, categorias, hogares, ingresos, presupuesto, gastos_comunes, ahorro, gastos_periodicos

app = FastAPI(title="Gestor de Gastos API", version="2.0.0")

app.include_router(usuarios.router)
app.include_router(gastos.router)
app.include_router(categorias.router)
app.include_router(hogares.router)
app.include_router(ingresos.router)
app.include_router(presupuesto.router)
app.include_router(gastos_comunes.router)
app.include_router(ahorro.router)
app.include_router(gastos_periodicos.router)

@app.get("/")
def root():
    return {"mensaje": "API Gestor de Gastos v2.0 funcionando ✅"}