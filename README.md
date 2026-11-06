# Gestor de cola de triaje

Programa de terminal para la cola de una urgencia. Cada paciente tiene nombre, nivel de triaje y hora de llegada. El nivel 1 (crítico) se atiende antes que el 2 (urgente), y el 2 antes que el 3 (estándar). Dentro de un nivel, manda `arrived_at`. Si dos horas son iguales, manda el orden de registro.

La cola vive en memoria mientras corre el proceso.

## Cómo ejecutarlo

Hace falta Python 3.10 o superior. Está probado con Python 3.12.3. No instala paquetes.

```bash
python3 triage_queue.py
python3 triage_queue.py --help
python3 triage_queue.py --demo
```

El menú pide una opción:

1. Registrar paciente. Pide el nombre y el nivel (1, 2 o 3). La hora de llegada es el instante del alta, en UTC.
2. Llamar al siguiente.
3. Ver quién sigue, sin retirarlo.
4. Ver la cola en orden de atención.
5. Ver el conteo de los niveles 1, 2 y 3.
6. Ver un ejemplo de prioridad. Lo calcula una cola aparte y no toca la cola de la sesión.
0. Salir.

Una opción desconocida, un nombre vacío o un nivel distinto de 1, 2 o 3 vuelven a pedir el dato. Si se llama o se consulta el siguiente con la cola vacía, el programa escribe el motivo y sigue:

```text
La cola está vacía: no hay un paciente a quien llamar.
Siguiente paso: opción 1 para registrar una llegada.
```

`peek` sobre una cola vacía usa este texto: `La cola está vacía: no hay un siguiente paciente.`

## Cómo probarlo

```bash
python3 -m unittest discover -s tests -v
```

## Estructura

| Pieza | Responsabilidad |
| --- | --- |
| `triage_queue.py` | `Patient`, `TriageQueue`, el menú `TriageCLI` y el punto de entrada |
| `DESIGN.md` | Por qué hay tres colas, el coste de cada operación y el orden del lock |
| `tests/test_triage_queue.py` | Orden, bordes, menú, entrada real del proceso y dos workers |

`main()` solo distingue `--help`, `--demo` y el menú. El alta, la extracción y el listado están en `TriageQueue`.

## Operaciones

| Método | Efecto |
| --- | --- |
| `enqueue(patient)` | Mete al paciente en la cola de su nivel, según `arrived_at` |
| `dequeue()` | Extrae al siguiente. Si no hay nadie, lanza `EmptyQueueError` |
| `peek()` | Devuelve al siguiente sin extraerlo. Si no hay nadie, lanza `EmptyQueueError` |
| `list_queue()` | Lista nueva con quienes esperan, en orden de atención |
| `stats()` | Diccionario `{1: n, 2: n, 3: n}` |

## Ejemplo

La salida de `python3 triage_queue.py --demo` es esta:

```text
Ejemplo de prioridad
Este ejemplo no modifica la cola actual.

Registro, en este orden:
1. Ana — nivel 3 (estándar) — llegada 2026-11-06T10:00:00+00:00
2. Luis — nivel 2 (urgente) — llegada 2026-11-06T10:01:00+00:00
3. Marta — nivel 1 (crítico) — llegada 2026-11-06T10:02:00+00:00
4. Nora — nivel 2 (urgente) — llegada 2026-11-06T10:03:00+00:00

Orden de atención:
1. Marta — nivel 1 (crítico) — llegada 2026-11-06T10:02:00+00:00
2. Luis — nivel 2 (urgente) — llegada 2026-11-06T10:01:00+00:00
3. Nora — nivel 2 (urgente) — llegada 2026-11-06T10:03:00+00:00
4. Ana — nivel 3 (estándar) — llegada 2026-11-06T10:00:00+00:00

Marta llegó la tercera y se atiende la primera: el nivel 1 pasa por delante del 2 y del 3.
Luis se atiende antes que Nora: los dos son nivel 2 y Luis llegó antes.
```

Ana entra primero y se atiende la última porque es nivel 3. Luis queda antes que Nora porque los dos son nivel 2 y su hora de llegada es anterior. Marta, registrada la tercera, pasa delante por ser nivel 1.
