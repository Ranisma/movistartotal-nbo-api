"""Inicialización segura del paquete FastAPI.

El repositorio base es relativamente pequeño y se construye una sola vez al importar
el paquete. La capa universal de 100k clientes sigue siendo lazy y se protege en
`preparar_mt` contra cargas concurrentes. Esto evita que un arranque frío con varias
requests simultáneas construya múltiples instancias de NBORepository en paralelo.
"""

from .repository import get_repository

# Llena la caché de get_repository antes de que FastAPI empiece a atender tráfico.
# NBORepository.__init__ NO carga decisiones_cliente.csv.gz.
get_repository()
