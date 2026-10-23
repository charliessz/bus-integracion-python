import logging
import os
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bus-integracion")

app = FastAPI(
    title="Bus de integración",
    description="Demostración académica de enrutamiento y transformación.",
    version="1.0.0",
)

catalogo = FastAPI(title="Servicio de catálogo")
notificaciones = FastAPI(title="Servicio de notificaciones")


PRODUCTOS = {
    "P001": {
        "codigo": "P001",
        "descripcion": "Teclado",
        "valor_unitario": 80000,
        "existencias": 10,
    },
    "P002": {
        "codigo": "P002",
        "descripcion": "Mouse",
        "valor_unitario": 45000,
        "existencias": 20,
    },
    "P003": {
        "codigo": "P003",
        "descripcion": "Monitor",
        "valor_unitario": 650000,
        "existencias": 5,
    },
}


class MensajeBus(BaseModel):
    tipo: Literal["consultar_producto", "solicitar_pedido"]
    codigo_producto: str = Field(min_length=1, max_length=20)
    cantidad: int = Field(default=1, ge=1, le=100)


class Aviso(BaseModel):
    id_solicitud: str
    asunto: str
    mensaje: str


@catalogo.get("/productos/{codigo}")
async def consultar_catalogo(codigo: str):
    producto = PRODUCTOS.get(codigo.upper())

    if producto is None:
        raise HTTPException(
            status_code=404,
            detail="El producto no existe.",
        )

    return producto


@notificaciones.post("/enviar")
async def registrar_notificacion(aviso: Aviso):
    logger.info(
        "NOTIFICACION DEMO | solicitud=%s | asunto=%s | mensaje=%s",
        aviso.id_solicitud,
        aviso.asunto,
        aviso.mensaje,
    )

    return {
        "registrada": True,
        "canal": "log_demostracion",
        "id_solicitud": aviso.id_solicitud,
    }


app.mount("/catalogo", catalogo)
app.mount("/notificaciones", notificaciones)


@app.get("/")
async def inicio():
    return {
        "proyecto": "Bus de integración",
        "estado": "Activo",
        "documentacion": "/docs",
        "servicios": [
            "/catalogo/docs",
            "/notificaciones/docs",
        ],
    }


@app.get("/salud")
async def salud():
    return {"estado": "ok"}


@app.post("/bus/mensajes")
async def procesar_mensaje(mensaje: MensajeBus):
    id_mensaje = str(uuid4())
    codigo = mensaje.codigo_producto.strip().upper()

    puerto = os.getenv("PORT", "8000")
    base_url = f"http://127.0.0.1:{puerto}"

    logger.info(
        "BUS | id=%s | tipo=%s | producto=%s",
        id_mensaje,
        mensaje.tipo,
        codigo,
    )

    try:
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=15.0,
            trust_env=False,
        ) as cliente:
            respuesta_catalogo = await cliente.get(
                f"/catalogo/productos/{codigo}"
            )
            respuesta_catalogo.raise_for_status()
            original = respuesta_catalogo.json()

            producto = {
                "id": original["codigo"],
                "nombre": original["descripcion"],
                "precio": original["valor_unitario"],
                "stock": original["existencias"],
                "moneda": "COP",
            }

            if mensaje.tipo == "consultar_producto":
                return {
                    "id_mensaje": id_mensaje,
                    "ruta": ["bus", "catalogo"],
                    "producto": producto,
                }

            if mensaje.cantidad > producto["stock"]:
                raise HTTPException(
                    status_code=409,
                    detail="No hay existencias suficientes.",
                )

            total = producto["precio"] * mensaje.cantidad

            aviso = {
                "id_solicitud": id_mensaje,
                "asunto": "Nueva solicitud de pedido",
                "mensaje": (
                    f"Producto: {producto['nombre']}; "
                    f"cantidad: {mensaje.cantidad}; "
                    f"total: {total} COP."
                ),
            }

            respuesta_aviso = await cliente.post(
                "/notificaciones/enviar",
                json=aviso,
            )
            respuesta_aviso.raise_for_status()

            return {
                "id_mensaje": id_mensaje,
                "ruta": ["bus", "catalogo", "notificaciones"],
                "estado": "solicitud_notificada",
                "producto": producto,
                "cantidad": mensaje.cantidad,
                "total": total,
                "notificacion": respuesta_aviso.json(),
            }

    except httpx.HTTPStatusError as error:
        if error.response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail="El producto solicitado no existe.",
            ) from error

        raise HTTPException(
            status_code=502,
            detail="Un servicio integrado devolvió un error.",
        ) from error

    except httpx.RequestError as error:
        raise HTTPException(
            status_code=502,
            detail="No fue posible conectar con un servicio integrado.",
        ) from error
