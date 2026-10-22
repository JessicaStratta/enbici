"""Línea de base reproducible para ENBICI.

Ejecutar desde la raíz del repositorio: python evaluacion/prueba_inicial.py
Guarda evaluacion/resultados_originales.csv.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.graph.loader import load_montevideo_graph
from src.routing.pathfinder import compute_route_metrics, find_route, nearest_node

# Coordenadas tomadas de main.py del repositorio de ENBICI: latitud, longitud.
LUGARES = {
    "Plaza Independencia": (-34.9060, -56.1996),
    "Facultad de Ingeniería": (-34.8947, -56.1520),
}
ESCENARIOS = [
    ("Plaza Independencia", "Facultad de Ingeniería"),
    ("Facultad de Ingeniería", "Plaza Independencia"),
]
PESOS_ELEVACION = [0, 3, 5, 10]


def git_output(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "desconocido"


def main() -> None:
    destino_csv = ROOT / "evaluacion" / "resultados_originales.csv"
    destino_csv.parent.mkdir(parents=True, exist_ok=True)

    print("Cargando grafo de Montevideo...")
    G = load_montevideo_graph()
    print(f"Grafo cargado: {G.number_of_nodes()} nodos, {G.number_of_edges()} aristas")

    version = git_output("rev-parse", "HEAD")
    cambios_sin_guardar = bool(git_output("status", "--porcelain"))
    marca_tiempo = datetime.now(timezone.utc).isoformat()
    filas = []

    for origen, destino in ESCENARIOS:
        nodo_origen = nearest_node(G, *LUGARES[origen])
        nodo_destino = nearest_node(G, *LUGARES[destino])
        for peso in PESOS_ELEVACION:
            print(f"Probando {origen} -> {destino} | peso={peso}")
            inicio = time.perf_counter()
            try:
                ruta = find_route(
                    G, nodo_origen, nodo_destino,
                    elevation_weight=peso,
                    wind_weight=0.0,
                    allow_parks=True,
                    max_against_traffic_blocks=0,
                )
                duracion = time.perf_counter() - inicio
                metricas = compute_route_metrics(G, ruta, elevation_weight=peso)
                filas.append({
                    "origen": origen,
                    "destino": destino,
                    "peso_elevacion": peso,
                    "peso_viento": 0,
                    "permite_senderos": True,
                    "permite_contramano": False,
                    "distancia_km": round(metricas.total_distance_m / 1000, 4),
                    "desnivel_positivo_m": round(metricas.total_elevation_gain_m, 2),
                    "tiempo_algoritmo_s": round(duracion, 4),
                    "cantidad_nodos": metricas.node_count,
                    "identificador_ruta": hashlib.sha256(
                        ",".join(str(n) for n in ruta).encode("utf-8")
                    ).hexdigest()[:16],
                    "estado": "OK",
                    "error": "",
                    "git_commit": version,
                    "cambios_locales": cambios_sin_guardar,
                    "fecha_utc": marca_tiempo,
                })
            except Exception as exc:
                filas.append({
                    "origen": origen,
                    "destino": destino,
                    "peso_elevacion": peso,
                    "peso_viento": 0,
                    "permite_senderos": True,
                    "permite_contramano": False,
                    "estado": "ERROR",
                    "error": f"{type(exc).__name__}: {exc}",
                    "git_commit": version,
                    "cambios_locales": cambios_sin_guardar,
                    "fecha_utc": marca_tiempo,
                })

    df = pd.DataFrame(filas)
    df.to_csv(destino_csv, index=False, encoding="utf-8-sig")
    print("\nResultados:")
    columnas = ["origen", "destino", "peso_elevacion", "distancia_km", "desnivel_positivo_m", "tiempo_algoritmo_s", "estado"]
    print(df.reindex(columns=columnas).to_string(index=False))
    print(f"\nCSV guardado: {destino_csv}")
    if cambios_sin_guardar:
        print("AVISO: hay archivos modificados o nuevos; el hash de commit por sí solo no describe todo el entorno.")


if __name__ == "__main__":
    main()
