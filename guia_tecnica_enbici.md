# ENBICI — Guía técnica del repositorio para comprenderlo, modificarlo y evaluarlo

**Proyecto:** [JessicaStratta/enbici](https://github.com/JessicaStratta/enbici) (fork de `martinferreirab/enbici`)  
**Propósito:** explicación de arquitectura, archivos, decisiones técnicas, puntos de mejora y criterios de evaluación para el trabajo de tesis.

> **Alcance y precaución:** esta guía se basa en la estructura y el comportamiento identificados en la revisión previa de ENBICI, y en el script de evaluación preparado para este proyecto. No se pudo descargar una versión actualizada del fork al redactarla; por tanto, no es una auditoría línea por línea del commit actual. El fork podría incorporar cambios recientes o archivos adicionales. Para usarla como documentación definitiva, contrastá sus descripciones con los archivos de tu rama y registrá el hash de Git de la versión estudiada.

## 1. Qué hace ENBICI, explicado en una frase

ENBICI construye una red vial de Montevideo como un **grafo dirigido** y busca un camino desde un origen hasta un destino minimizando un **costo generalizado** que depende de distancia, pendientes, viento y preferencias de circulación. No predice el comportamiento del ciclista mediante machine learning: resuelve un problema de **camino mínimo en un grafo ponderado**, empleando Dijkstra.

**Dos conceptos distintos:**

1. **Función de costo:** decide qué segmentos convienen y cuánto «cuestan». Se define principalmente en `src/routing/cost.py`.
2. **Algoritmo de búsqueda:** encuentra la combinación de segmentos cuyo costo total es menor. Se coordina desde `src/routing/pathfinder.py`.

Que Dijkstra encuentre el camino óptimo **según la función** no garantiza que sea la ruta físicamente menos cansadora, más segura o más agradable. Esa correspondencia necesita **validación empírica**.

## 2. Cómo se conectan los componentes

```text
OpenStreetMap ──────> src/graph/loader.py ──> grafo de calles (nodos y aristas)
                               │
Open-Meteo elevación ─> src/graph/elevation.py
                         + scripts/enrich_elevation_idw.py
                               │
                               ▼
                     Grafo enriquecido/caché
                               │
Usuario: origen/destino ─> src/utils/geocoding.py ──> coordenadas
                               │
                               ▼
                src/routing/pathfinder.py
                     │               ▲
                     │               │
                     ▼               │
             src/routing/cost.py <── src/api/weather.py
                     │               (viento)
                     ▼
            Ruta de menor costo
               │           │
               ▼           ▼
   src/visualization/   Métricas de distancia,
       map_export.py     desnivel, nodos, etc.
               │           │
               └─────┬─────┘
                     ▼
             app_streamlit.py
        o src/api/app.py (FastAPI)
```

**Flujo temporal:** la carga y el enriquecimiento del grafo se hacen antes o al iniciar el sistema; la búsqueda y la ponderación de costos ocurren cada vez que se calcula una ruta. El viento puede depender de una consulta meteorológica realizada en el momento.

## 3. Glosario mínimo

- **Nodo:** intersección o punto de conexión del mapa, con latitud/longitud y potencialmente elevación.
- **Arista:** tramo de calle/sendero que une nodos; puede tener dirección, longitud, pendiente y otras etiquetas.
- **Grafo dirigido:** circular de A a B no garantiza que se permita circular de B a A.
- **Peso de arista:** número que se suma al costo de una ruta al utilizar ese tramo.
- **Dijkstra:** algoritmo que encuentra el camino de menor costo acumulado con pesos no negativos.
- **Caché:** archivo que almacena un grafo ya preparado para evitar descargar y procesar todo repetidamente.
- **IDW:** interpolación espacial que estima valores desconocidos usando puntos cercanos, ponderados por distancia.
- **Línea de base (baseline):** resultados obtenidos con la versión original, bajo condiciones fijas, contra los cuales se compararán mejoras.

---

# 4. Descripción archivo por archivo

## A. Preparación del grafo y de la elevación

### `src/graph/loader.py` — Construcción y carga del mapa

**Qué hace:** centraliza la carga de la red vial de Montevideo. Puede descargar o leer desde el almacenamiento local el grafo que utilizarán todos los cálculos. En la API que hemos empleado, su función principal es `load_montevideo_graph()`.

**Estrategias:** OSMnx/OpenStreetMap para obtener calles y conectividad; representar nodos y aristas con NetworkX; evitar reprocesamientos mediante caché. La dirección de las aristas importa para calles de una sola mano. El código revisado previamente contempla representación de contramano bajo determinadas condiciones.

**Entradas:** datos cartográficos, configuraciones de carga y archivos en `data/`. **Salida:** un objeto grafo que pasan a usar las funciones de ruteo.

**Si lo modificás:** puede cambiar la cobertura de calles, la legalidad de los recorridos, la cantidad de caminos disponibles y, en consecuencia, todas las rutas. **Cómo evaluar:** número de nodos/aristas, componentes conectadas, cobertura, longitud mínima, sentido de circulación, número de rutas imposibles, hash/versionado del grafo.

**Riesgo:** un cambio en el grafo invalida comparaciones con una línea de base que usó otro grafo, salvo que sea justamente lo que se está evaluando.

### `src/graph/elevation.py` — Altura y pendiente de los tramos

**Qué hace:** aporta datos de altitud a los nodos y deriva pendientes a partir de la diferencia de altura y la longitud de la arista. Se usa después al penalizar subidas y al informar desnivel positivo.

**Estrategia:** la pendiente se aproxima como `(altura_destino - altura_origen) / longitud`. Subidas positivas, bajadas negativas. El componente de costo limita la magnitud de pendiente utilizada para evitar valores extremos.

**Entradas:** grafo, elevaciones y longitudes. **Salida:** atributos topográficos por nodo/arista.

**Si lo modificás:** afectará la percepción de dificultad de cada subida y el desnivel acumulado calculado. **Cómo evaluar:** error de elevación frente a una fuente independiente, error de pendiente, distribución de pendientes, anomalías y diferencias de rutas para configuraciones idénticas.

**Riesgo:** el desnivel es tan confiable como el modelo de elevación. Calles cortas amplifican errores en altura al calcular pendiente.

### `scripts/enrich_elevation_idw.py` — Enriquecimiento por interpolación espacial

**Qué hace:** construye una versión del grafo con elevaciones sin consultar individualmente todos los nodos. Es una etapa de preparación de datos, no el motor de búsqueda de rutas.

**Estrategia documentada:** obtener alturas en una muestra espacial de aproximadamente 1.500 nodos y estimar las restantes por interpolación inversa de distancias, utilizando hasta ocho vecinos y potencia dos: `altura_estimada = suma(altura_i / distancia_i²) / suma(1 / distancia_i²)`.

**Si lo modificás:** podés variar número/distribución de muestras, vecinos, potencia, fuente de altimetría o tratamiento de valores atípicos. **Cómo evaluar:** apartar puntos con elevación conocida como conjunto de validación; medir MAE/RMSE y analizar errores por barrio/pendiente; comparar rutas usando un mismo banco de orígenes y destinos.

**Riesgo:** tener un gráfico lindo de alturas no demuestra exactitud. La interpolación puede suavizar repechos reales.

### `enrich_elevation.py` — Alternativa de enriquecimiento de elevaciones

**Qué hace:** script alternativo/previo que intenta obtener elevaciones de muchos o todos los nodos con consultas más directas, en vez de depender de la interpolación IDW.

**Estrategia:** consultas de altitud más numerosas; potencialmente mayor consumo de API y tiempo, a cambio de depender menos de la interpolación (no implica que los datos obtenidos sean exactos).

**Si lo modificás:** compará cobertura, cantidad de peticiones, tiempo de enriquecimiento, tasas de error y precisión de las pendientes. **Precaución:** no mezclar un grafo generado con este proceso con uno generado por IDW sin identificar cuál se utilizó.

### `data/montevideo.graphml` — Grafo en formato interoperable

**Qué contiene:** nodos, aristas y atributos serializados en formato GraphML. **Para qué sirve:** persistencia e intercambio del grafo base o preparado.

**No es código.** Cambiarlo puede afectar todos los resultados. Conviene versionar su procedencia, fecha, tamaño, cantidad de nodos/aristas y su hash SHA-256.

### `data/montevideo_final.pkl` — Grafo preparado en Python

**Qué contiene:** versión serializada con `pickle`, utilizada para recargar el grafo con rapidez.

**Estrategia:** acelerar el arranque evitando reconstrucciones. **Riesgo:** puede quedar desactualizado frente a `graphml` u otros datos; en ese caso la aplicación podría continuar usando una versión antigua. Los archivos pickle deben cargarse solo desde fuentes confiables.

**Para experimentos:** congelar un archivo de grafo de referencia, calcular su hash y asegurar que antes/después lean **el mismo archivo**.

### `data/`, `cache/` y `output/` — Carpeta de datos y artefactos

- `data/`: insumos geográficos y versiones del grafo.
- `cache/`: archivos intermedios para no repetir trabajo.
- `output/`: mapas HTML y otros productos de ejecución.

**Precaución:** no confundir insumos, cachés y resultados: una nueva ejecución puede sobrescribir un HTML o un CSV. Guardar experimentos con identificadores y fechas.

## B. Algoritmo de rutas y función objetivo

### `src/routing/cost.py` — Cuánto «cuesta» circular por un tramo

**Qué hace:** asigna a cada segmento un costo ajustado por criterios elegidos. Es probablemente el lugar más importante para innovar en la tesis.

**Modelo descrito en la revisión anterior (forma conceptual):**

`costo_tramo = longitud × factor_pendiente × factor_viento × factor_sendero × factor_contramano`

Para subidas, el componente base es aproximadamente:

`factor_pendiente = 1 + peso_elevacion × max(pendiente_positiva, 0)^1.5`

Con pendiente acotada a un máximo del 25 % para ese cálculo. La penalización por viento combina velocidad, dirección del desplazamiento y un parámetro de preferencia. Los senderos identificados por ciertas etiquetas OSM pueden recibir un multiplicador preferente de 0,5, o uno alto de 10 cuando se deshabilitan. Para contramano se ha utilizado prohibición por costo infinito si no está permitida y penalización elevada si está tolerada.

**Estrategia:** heurística multicriterio **multiplicativa**: permite representar preferencias sin cambiar Dijkstra. **Limitación central:** sus pesos y formas funcionales deben justificarse y validarse; no equivalen automáticamente a energía real, tiempo ni riesgo.

**Si lo modificás:** se pueden incorporar nuevas variables (ciclovías, tipo de vía, velocidades, seguridad, estado del pavimento), recalibrar pesos o probar una formulación aditiva. **Cómo evaluar:** usar rutas de igual origen-destino, comparar métricas independientes de la función objetivo, analizar sensibilidad por grupo de ciclistas y verificar ausencia de decisiones peligrosas.

**Advertencia metodológica:** no es válido demostrar que la nueva fórmula «mejoró» porque da un costo menor calculado con **esa misma fórmula**. El criterio de evaluación debe ser externo o fijo.

### `src/routing/pathfinder.py` — Búsqueda de la mejor ruta según el costo

**Qué hace:** ubica nodos cercanos a coordenadas (`nearest_node`), encuentra rutas (`find_route`) y calcula sus indicadores (`compute_route_metrics`).

**Estrategia:** Dijkstra sobre grafo dirigido ponderado; suma costos de aristas y busca el mínimo. Entrega una secuencia de nodos y métricas como longitud, desnivel y cantidad de nodos. Si existen varias aristas entre dos nodos, conviene verificar con cuál se calcula el costo y las métricas.

**Si lo modificás:** podés estudiar Dijkstra frente a A*, mejorar tiempo de respuesta o agregar alternativas. **Cómo evaluar:** comparaciones de costo mínimo sobre la misma función y grafo, tiempo mediano de cálculo tras calentamiento, rutas sin solución, estabilidad, consumo de memoria, reproducibilidad.

**Riesgo:** cambiar Dijkstra por otro algoritmo no implica mejor calidad de ruta por sí mismo: si ambos encuentran el óptimo de la misma función, deberían hallar el mismo costo mínimo (aunque existan empates).

## C. Meteorología, búsqueda y visualización

### `src/api/weather.py` — Obtención y asignación del viento

**Qué hace:** consulta datos meteorológicos de Open-Meteo para incorporar dirección y velocidad del viento al cálculo.

**Estrategia:** uso de cuatro ubicaciones de referencia para Montevideo; asociación de cada segmento con la estación/punto más cercano. La dirección relativa al movimiento determina cuánto viento se considera frontal.

**Si lo modificás:** podés estudiar interpolación espacial de viento, información histórica, actualización temporal o modelos físicos de potencia. **Cómo evaluar:** comparar frente a observaciones independientes, variación de rutas por escenarios fijos de viento, comportamiento ante API caída y efecto de caché.

**Clave experimental:** la meteorología cambia con el tiempo. Para comparar algoritmos hay que **congelar un escenario meteorológico** o usar datos históricos idénticos.

### `src/utils/geocoding.py` — De nombres de lugares a coordenadas

**Qué hace:** transforma textos como «Plaza Independencia» en coordenadas geográficas, utilizando servicios de geocodificación como Nominatim.

**Estrategia:** separar la búsqueda de nombres del algoritmo sobre el grafo. Luego las coordenadas se asocian a nodos cercanos.

**Si lo modificás:** podrías mejorar desambiguación, búsqueda, tratamiento de resultados fuera de Montevideo y distancia entre la dirección pedida y el nodo elegido. **Cómo evaluar:** tasa de búsquedas exitosas, errores de localización, distancia de ajuste al grafo y casos ambiguos.

**Clave:** si el punto seleccionado cambia entre corridas, la comparación del algoritmo deja de ser válida. En los benchmarks se deben usar **coordenadas fijas**, no volver a geocodificar cada vez.

### `src/visualization/map_export.py` — Generación de mapas

**Qué hace:** convierte la secuencia de nodos de la ruta en un mapa HTML interactivo mediante Folium, incorporando líneas, marcadores u otros detalles.

**Estrategia:** separar el cálculo de la ruta de su presentación cartográfica. Las teselas o imágenes del mapa de fondo son un servicio externo.

**Si lo modificás:** cambia la visualización, **no debería cambiar el recorrido**. Podés mejorar colores, leyendas, mapas comparativos, perfil altimétrico y proveedor de mosaicos.

**Ejemplo de error conocido:** un fondo con respuesta HTTP 403 puede bloquear la visualización aun cuando la línea de ruta y las métricas estén bien. Cambiar `tiles="OpenStreetMap"` por un proveedor compatible (por ejemplo `"CartoDB positron"`, sujeto a términos de uso) afecta el mapa mostrado, no Dijkstra.

## D. Aplicaciones e interfaz de servicio

### `app_streamlit.py` — Aplicación interactiva en navegador

**Qué hace:** reúne los formularios de origen/destino, parámetros ajustables, ejecución del ruteo y presentación de mapas y métricas.

**Estrategia:** Streamlit para prototipado rápido de la interfaz. Según la versión revisada, llama directamente a los módulos Python de ENBICI; no necesita pasar por FastAPI.

**Si lo modificás:** podés agregar comparación de dos rutas, visualización de penalizaciones, explicaciones y descarga de métricas. **Cómo evaluar:** pruebas funcionales, claridad, tasa de éxito de usuario, tiempo total y consistencia entre opciones y resultados.

### `src/api/app.py` — API web del motor

**Qué hace:** ofrece una interfaz HTTP, principalmente `GET /route` para calcular rutas y `GET /health` para comprobar que el servicio responde.

**Estrategia:** FastAPI: separar la lógica del servidor y permitir que otro cliente —por ejemplo una futura app móvil— use el motor.

**Si lo modificás:** cambia la manera en que clientes externos piden o reciben rutas. **Cómo evaluar:** pruebas de endpoints, validación de entrada, códigos de error, latencia total, contrato JSON y casos fuera del área de cobertura.

### `src/api/schemas.py` — Contrato de datos de la API

**Qué hace:** organiza los campos y tipos que la API acepta o devuelve; usualmente con esquemas o modelos de validación.

**Estrategia:** estandarizar respuestas y evitar estructuras arbitrarias. **Cómo evaluar:** compatibilidad de formatos, tipos, campos faltantes y validación de coordenadas/parámetros.

### `run_server.py` — Arranque de FastAPI

**Qué hace:** sirve como punto de entrada para poner en marcha el servidor de la API, normalmente a través de Uvicorn.

**Si lo modificás:** suele cambiar configuración de inicio (puerto, host, entorno), no la lógica de elección de rutas.

## E. Programas de demostración, pruebas y evaluación

### `main.py` — Demostración de línea de base

**Qué hace:** ejecuta una comparación programada, con el recorrido Plaza Independencia → Facultad de Ingeniería y distintos pesos de elevación; guarda o muestra resultados.

**Estrategia:** ejemplo manual y prueba de humo para verificar que los módulos integrados operan.

**Limitación:** dos rutas o pocas configuraciones no permiten generalizar conclusiones sobre Montevideo.

### `scripts/test_elevation_routing.py` — Pruebas de sensibilidad a pendientes

**Qué hace:** ejecuta ejemplos para mostrar qué ocurre al variar la penalización por elevación, incluyendo recorridos de referencia (por ejemplo Plaza Independencia/Tres Cruces según el código revisado).

**Estrategia:** análisis de sensibilidad exploratorio. **Qué demuestra:** que el parámetro puede afectar los recorridos. **Qué no demuestra:** que las rutas son óptimas para personas reales.

### `evaluacion/README.md` — Protocolo de trabajo de tesis (archivo de tu fork)

**Qué hace:** documenta objetivos, variables, protocolos y criterios de éxito. Conviene convertirlo en la referencia metodológica de todo experimento.

### `evaluacion/prueba_inicial.py` — Primera batería de pruebas propuesta

**Qué hace:** utiliza `load_montevideo_graph`, `nearest_node`, `find_route` y `compute_route_metrics`. Prueba ida y vuelta entre Plaza Independencia y Facultad de Ingeniería con pesos de elevación 0, 3, 5 y 10 (8 combinaciones), sin viento, con senderos habilitados y contramano deshabilitada. Guarda `evaluacion/resultados_originales.csv`.

**Métricas:** distancia, ascenso, cantidad de nodos, duración del algoritmo, firma hash de nodos de ruta, éxito/error, revisión Git y presencia de modificaciones locales.

**Limitaciones:** muestra pequeña, sin medición de energía real ni validación externa; duración de una sola ejecución por escenario no es una buena estimación robusta de rendimiento. Si los resultados se ejecutan sobre versiones diferentes del grafo, no hay comparación limpia.

### `evaluacion/resultados_originales.csv` — Resultados de referencia

**Qué contiene:** una fila por escenario de prueba, cuando se haya ejecutado `prueba_inicial.py`. Debe conservarse sin sobrescribir y asociado a un commit y hash de datos.

**Estrategia recomendada:** nuevos resultados en archivos diferentes (`evaluacion/resultados/experimento_001.csv`, etc.). No reemplazar el original al probar cambios.

## F. Configuración y documentación

### `pyproject.toml` — Declaración del proyecto Python

**Qué hace:** lista dependencias, versión mínima de Python (identificada previamente como Python 3.12) y metadatos del proyecto.

**Si lo modificás:** puede alterar el entorno de ejecución. Comparaciones de rendimiento requieren ambientes compatibles.

### `uv.lock` — Congelamiento de dependencias

**Qué hace:** registra versiones de paquetes para reproducir el ambiente mediante el gestor `uv`.

**Estrategia:** reducir diferencias entre computadoras y corridas. En Colab, una instalación manual con `%pip install` que no respete el lock puede usar otras versiones.

### `.gitignore` — Archivos que Git no debe subir

**Qué hace:** excluye artefactos temporales, cachés y entornos que no corresponda versionar. Puede ser necesario revisar qué resultados de `evaluacion/` conviene conservar y si alguna regla impide subirlos.

### `README.md` — Presentación general del repositorio

**Qué hace:** debería explicar objetivos, instalación, ejecución y estructura. En la revisión anterior figuraba vacío o insuficiente.

**Mejora rápida:** completar instrucciones reproducibles para ejecutar el sistema y distinguir versión científica, demo y API.

### `journey.md` — Bitácora del desarrollo

**Qué hace:** registra decisiones y etapas del compañero, incluyendo construcción de datos, cambios de diseño, cifras orientativas del grafo y prioridades.

**Uso para tesis:** reconstruir evolución, criterios de diseño y decisiones de implementación. Distinguir siempre intenciones anotadas de funcionalidades realmente presentes en código.

### `next_steps.md` — Trabajo futuro propuesto

**Qué hace:** ideas y posibles pendientes. No equivale a código implementado.

**Uso para tesis:** generar hipótesis de mejora que luego se puedan medir, ordenar y justificar.

### `to_app.md.md` — Idea/especificación de aplicación móvil

**Qué hace:** describe una posible aplicación cliente, con React Native/Expo según la revisión previa.

**Uso para tesis:** separación de motor/API y experiencia de usuario. La existencia de este documento no significa que la app móvil esté implementada.

### Archivos `__init__.py` (si aparecen dentro de `src/`)

**Qué hacen:** permiten organizar carpetas como paquetes importables en Python. Normalmente no contienen la lógica matemática principal; cualquier contenido adicional debe revisarse caso por caso.

---

# 5. Las decisiones técnicas principales y sus alternativas

| Decisión actual | Ventaja | Posible limitación | Qué experimento haría |
|---|---|---|---|
| Grafo de OpenStreetMap/OSMnx | Cobertura, conectividad y atributos | Etiquetas incompletas, problemas legales/ciclistas | Auditar rutas contra infraestructura ciclista conocida |
| Elevaciones estimadas por IDW | Menos consultas y procesamiento | Suavizado y sesgos locales | Validación espacial MAE/RMSE contra puntos no usados |
| Pendiente con penalización `p^1.5` | Simple y fácil de ajustar | Forma y pesos heurísticos | Sensibilidad + validación con esfuerzo real o modelo físico |
| Penalizaciones multiplicativas | Fácil combinar atributos | Escalas y compensaciones difíciles de interpretar | Comparar normalización o formulación aditiva |
| Viento por cuatro referencias | Bajo costo y simplicidad | Baja resolución espacial; cambios temporales | Viento fijo frente a viento espacial/histórico |
| Dijkstra | Óptimo respecto al costo definido | Cálculo repetido en grafo grande | A* admisible para acelerar, verificando mismo costo óptimo |
| Preferencia por senderos OSM | Una forma simple de priorizar ciertas vías | `path`/`footway` no garantiza parque o circulación legal | Clasificación específica de ciclovías y vías habilitadas |
| Penalización por contramano | Implementación rápida | No es un límite real de «cuadras», puede tolerar rutas inseguras | Restricciones duras y pruebas de cumplimiento |
| Grafo serializado y caché | Mayor velocidad de arranque | Datos obsoletos y mala trazabilidad | Hash del grafo y política de regeneración |
| Streamlit + FastAPI | Demo rápida y API reutilizable | Posibles diferencias entre clientes y parámetros | Pruebas de contrato e integración |

# 6. ¿Dónde conviene modificar primero?

### Prioridad 1 — Evaluación confiable (aporte fuerte a la tesis, poco riesgo)

Ampliar `evaluacion/` a 100–200 pares de origen/destino representativos, incluyendo ida y vuelta, recorridos cortos/largos, zonas llanas/con pendiente. Congelar el grafo y las condiciones del viento. Guardar las rutas, indicadores, tiempos repetidos y firmas de versión. Incorporar pruebas de seguridad: ¿se respetan sentidos de calles y restricciones?

**Éxito:** poder afirmar con números, tablas y gráficos qué cambia, para cuántas rutas, y con qué magnitud.

### Prioridad 2 — Calibración del costo (`cost.py`)

Probar una modificación a la vez, por ejemplo la forma de penalizar pendiente o el peso de ciclovías. Mantener conjunto de pruebas fijo. Evaluar distancia, ascenso, desviaciones de seguridad, esfuerzo estimado con modelo externo y aceptación del usuario.

**Éxito:** mejora de métricas independientes, no simplemente reducción del costo de la fórmula propia.

### Prioridad 3 — Calidad de elevación (`elevation.py`, IDW)

Validar error altimétrico, luego explorar otras fuentes o resoluciones. Recalcular rutas solo después de demostrar que la entrada mejoró.

**Éxito:** menor error topográfico medido contra referencias externas.

### Prioridad 4 — Seguridad y legalidad (`loader.py`, `cost.py`)

Prohibir aristas no habilitadas o modelar restricciones reales en lugar de convertir todo en penalizaciones blandas. Revisar identificación de senderos, ciclovías y contramano.

**Éxito:** cero infracciones de las restricciones evaluadas en la batería de prueba, sin perder cobertura injustificadamente.

### Prioridad 5 — Rendimiento (`pathfinder.py`)

Recién después de fijar la función objetivo, comparar Dijkstra con A*. Para A* hace falta una heurística admisible: no debe sobreestimar el costo remanente si se quiere mantener optimalidad.

**Éxito:** menor tiempo en un conjunto amplio de casos, con el **mismo costo óptimo** y las mismas restricciones.

# 7. Cómo comparar «antes» y «después» sin engañarnos

**Antes de editar:** guardar commit, estado de Git, hash del grafo y parámetros. Usar coordenadas fijas, peso de viento = 0 o escenarios de viento fijos, igual entorno y proveedor de datos. No sobrescribir `resultados_originales.csv`.

**Después de editar:** correr exactamente los mismos casos, guardar CSV nuevo, comparar por par origen-destino y configuración. Para tiempos, ejecutar repetidamente y comparar medianas en el mismo tipo de entorno; las máquinas de Colab pueden variar.

**Medidas de calidad recomendadas:**

- Distancia real (m).
- Desnivel positivo (m).
- Pendiente máxima y proporción de ruta con pendiente elevada.
- Cantidad/longitud de aristas potencialmente no habilitadas.
- Porcentaje de recorrido por infraestructura ciclista confirmada (si se incorporan datos fiables).
- Esfuerzo/energía estimada por un modelo externo **validado** o datos de ciclistas reales, si se consiguen.
- Tiempo mediano y percentiles de cálculo.
- Tasa de casos con ruta válida.
- Distribución del cambio (% de rutas que mejoran, empeoran o empatan según indicadores predefinidos).

**Tres errores metodológicos a evitar:**

1. Usar la función de costo propuesta como juez único de su propia mejora.
2. Cambiar simultáneamente código, grafo, coordenadas y viento, de modo que no se sepa qué generó las diferencias.
3. Comparar una sola ruta y generalizar sus resultados a toda la ciudad.

## 8. Ejemplo de experimento de tesis

**Hipótesis:** priorizar mejor las calles con infraestructura ciclista reduce la exposición a tramos de circulación menos adecuados sin aumentar excesivamente la distancia.

**Intervención:** agregar en `cost.py` un factor de preferencia **solo para infraestructura ciclista explícitamente identificada y autorizada** en los datos del grafo (posiblemente también adaptar `loader.py` para conservar esas etiquetas).

**Diseño:** seleccionar 150 pares origen-destino de diversos barrios y distancias; fijar coordenadas, versión de grafo y viento; ejecutar el algoritmo original y el modificado.

**Resultados a medir:** distancia adicional (%), desnivel adicional (m), proporción de infraestructura ciclista, infracciones/restricciones y tiempo de cálculo. Presentar promedios, medianas, dispersión y proporción de rutas que logran la mejora buscada.

**Criterio de decisión:** un intercambio explícito entre distancia y calidad/seguridad de la infraestructura, sin recurrir a un «costo» inventado como prueba concluyente.

# 9. Cómo obtener un inventario exacto de tu fork desde Colab

Para confirmar los archivos reales de tu rama y detectar los que no aparecen en esta guía, ejecutá desde la raíz de `enbici`:

```python
%cd /content/enbici
!git rev-parse HEAD
!git status --short
!git ls-files
```

Para identificar **funciones y clases** sin ejecutar sus archivos:

```python
from pathlib import Path
import ast

for archivo in sorted(Path('src').rglob('*.py')):
    print(f'\n### {archivo}')
    try:
        raiz = ast.parse(archivo.read_text(encoding='utf-8'))
    except (UnicodeDecodeError, SyntaxError) as error:
        print('No se pudo analizar:', error)
        continue
    for nodo in raiz.body:
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            print(' -', type(nodo).__name__, nodo.name)
```

Estos resultados permiten completar o corregir esta guía sin asumir que el fork sigue igual que la versión revisada anteriormente.

---

## 10. Resumen operativo: mapa de intervenciones

| Si querés mejorar… | Modificar primero | Comprobar con… |
|---|---|---|
| Precisión del terreno | `elevation.py`, `enrich_elevation_idw.py` | Error contra alturas independientes |
| Elección de rutas | `cost.py` | Métricas externas con mismo conjunto de rutas |
| Velocidad de respuesta | `pathfinder.py` | Tiempo y costo óptimo idéntico |
| Uso de ciclovías | `loader.py` + `cost.py` | % en ciclovías y restricciones de circulación |
| Legalidad/contramano | `loader.py` + `cost.py` | Auditoría de aristas no permitidas |
| Viento | `weather.py` + `cost.py` | Validación meteorológica y escenarios congelados |
| Búsqueda de direcciones | `geocoding.py` | Precisión y tasa de éxito |
| Visualización del mapa | `map_export.py` | Calidad visual y errores de teselas |
| Controles de la interfaz | `app_streamlit.py` | Experiencia de uso y consistencia |
| Servicio para app móvil | `api/app.py`, `api/schemas.py` | Pruebas del API |
| Medición para tesis | `evaluacion/` | Experimentos reproducibles y comparables |

**Consejo final:** mantené una rama experimental, anotá cada cambio y nunca evalúes dos versiones sin registrar también el grafo y las condiciones en que fueron ejecutadas. Una mejora demostrada en una batería reproducible es un aporte científico mucho más fuerte que una ruta que simplemente «parece mejor» en el mapa.
