# Estado de esta actividad

La tabla canónica de la cohorte (las 83 actividades, entrega, retroalimentación, material y calendario) vive en el Control Tower, no en la caja ni en este repositorio:

https://github.com/Picazo333/4geeks-control-tower/tree/estado-cohorte-2026-11-13/estado

Empieza por `ESTADO.md` de esa carpeta. La tabla es `4GEEKS_ESTADO_COHORTE.csv`. El calendario por submódulo (llegada a Architecture: lunes 14 dic 2026; entrega de las actividades 32, 33 y 40: lunes 7 dic 2026) está en `CALENDARIO.md`. El material de las actividades 19 a 73 está en `MATERIAL_DIDACTICO.csv`.

PR del estado (abierto, **sin merge**): https://github.com/Picazo333/4geeks-control-tower/pull/32

La caja solo apunta, desde `/workspace/INDICE_ESTADO.md`. Para refrescar entregas y retroalimentación del LMS, en el Control Tower: `python3 estado/refresh_estado.py` (el token va en el entorno; nunca se imprime ni se guarda en un repo).

Este repositorio tiene el código de la actividad y su checkpoint de auditoría. Un agente no hace merge ni envía nada al LMS. Un autor no audita su propio trabajo. No hay secretos en estos archivos.
