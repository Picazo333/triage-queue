# Notas de diseño

La cola de triaje tiene tres prioridades fijas. Dentro de cada una, el orden es la hora de llegada. Esas dos reglas deciden la estructura.

## Estructura elegida

`TriageQueue` guarda tres `collections.deque`, una para el nivel 1, otra para el 2 y otra para el 3. Cada puesto recuerda `(arrived_at, secuencia, patient)`.

`enqueue` solo toca la deque de ese nivel. Si la llegada nueva es posterior o igual a la última de ese nivel, hace `append` (O(1)). Si el registro trae una hora anterior, retrocede solo dentro de esa deque hasta el punto de inserción (O(k), k = pacientes de ese nivel). Los otros niveles no se mueven.

`dequeue` y `peek` miran el nivel 1, luego el 2 y luego el 3, y se quedan con el primero que tenga gente. Como máximo son tres comprobaciones y un `popleft`.

La secuencia de registro solo desempata dos `arrived_at` iguales. Así el orden es estable y, cuando el reloj coincide, se conserva el orden de alta. El menú sella `arrived_at` con `datetime.now(timezone.utc)` en el momento del alta, así que en la terminal el caso común es el `append`.

El campo `arrived_at` forma parte del modelo porque la cola se va a integrar después en otro programa. Ese programa puede construir el `Patient` con la hora real de puerta, distinta del momento en que llama a `enqueue`. Ordenar por esa hora, y no por el orden casual de la llamada, es el orden de llegada. La secuencia cubre el empate que el enunciado describe como FIFO.

## Comparación

| Alternativa | Qué haría aquí | Por qué no es la elegida |
| --- | --- | --- |
| Una sola `deque` | `append` y `popleft` en O(1) | El orden sería el de alta global. Un nivel 1 que entra con gente de nivel 2 y 3 ya dentro quedaría al final, salvo que se recorra o se reconstruya toda la cola en cada alta. |
| Una lista ordenada de todos | Insertar por `(nivel, llegada)` | Cada alta desplaza o reordena también a los otros niveles. El enunciado pide colocar un crítico sin reordenar toda la cola. |
| Tres colas separadas | Una deque por nivel | Es la estructura de este programa. El dominio tiene exactamente tres prioridades y no cambia. Un crítico entra en su deque y ya queda delante de los niveles 2 y 3. |
| `heapq` | Montículo con clave `(nivel, llegada, secuencia)` | La biblioteca estándar lo permite y este programa no lo usa. El alta sería O(log n) sobre el total, y `list_queue` tendría que copiar el montículo y vaciarlo, o no podría mostrar la cola sin destruirla. Con tres prioridades fijas, las tres deque dejan `list_queue` y `stats` directos. |
| `queue.PriorityQueue` | Montículo con candado de la biblioteca | El enunciado no la pide. Arrastra el mismo problema de listado que `heapq` y el candado no resuelve el orden de atención. El candado de este programa está puesto alrededor de la operación completa, no solo del montículo. |

`stats` es O(1): tres `len`. `list_queue` es O(n) porque tiene que devolver a quienes esperan. `peek` es O(1). `dequeue` es O(1). `enqueue` es O(1) cuando las llegadas de ese nivel vienen en orden, que es el uso del menú, y O(k) si hay que insertar una hora anterior en medio del nivel.

La cola no tiene tope. Cada paciente en espera ocupa un puesto hasta que `dequeue` lo extrae. No se descarta a nadie para ahorrar memoria.

## Mutación concurrente

El estado compartido son las tres deque y el contador de secuencia. Cada método público toma un `threading.RLock` durante toda la operación. No hace falta el GIL como garantía: el lock es el que delimita la reserva.

Orden cuando un worker llama al siguiente paciente:

1. Toma el lock.
2. Elige la primera deque no vacía entre el nivel 1, el 2 y el 3.
3. Hace `popleft`. Esa extracción reserva al paciente: ya no está en la cola.
4. Suelta el lock.
5. Atiende al paciente fuera del lock.

Orden cuando, a la vez, otro worker registra un nivel 1:

1. Toma el mismo lock.
2. Inserta solo en la deque del nivel 1.
3. Suelta el lock.

Si la llamada gana el lock, se lleva a quien ya era el siguiente. El crítico queda en el nivel 1 para la próxima llamada. Si el alta gana el lock, el crítico ya está colocado cuando el otro worker elige, y sale el primero si no había otro nivel 1 delante por hora de llegada.

Ninguno de los dos copia la estructura, la modifica y la vuelve a asignar. Por eso no se pierde un alta ni se extrae dos veces el mismo puesto. La atención clínica queda fuera del lock para que un ingreso no espere a que termine la consulta.

Dos hilos que solo llaman a `dequeue` sobre la misma cola se reparten pacientes distintos: el `popleft` ocurre dentro del lock, así que el segundo hilo ya no ve ese puesto.
