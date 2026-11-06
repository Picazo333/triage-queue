"""Gestor de cola de triaje para una urgencia.

Patient y TriageQueue son el modelo. TriageCLI es el menú.
La comparación de estructuras y la concurrencia están en DESIGN.md.
"""

from __future__ import annotations

import sys
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, NamedTuple

TRIAGE_LEVELS = (1, 2, 3)
LEVEL_LABEL = {1: "crítico", 2: "urgente", 3: "estándar"}

EMPTY_DEQUEUE_MESSAGE = "La cola está vacía: no hay un paciente a quien llamar."
EMPTY_PEEK_MESSAGE = "La cola está vacía: no hay un siguiente paciente."

DEMO_ARRIVALS = (
    ("Ana", 3, datetime(2026, 11, 6, 10, 0, tzinfo=timezone.utc)),
    ("Luis", 2, datetime(2026, 11, 6, 10, 1, tzinfo=timezone.utc)),
    ("Marta", 1, datetime(2026, 11, 6, 10, 2, tzinfo=timezone.utc)),
    ("Nora", 2, datetime(2026, 11, 6, 10, 3, tzinfo=timezone.utc)),
)


class EmptyQueueError(Exception):
    """dequeue o peek se llamaron sin pacientes en espera."""


class _InputClosed(Exception):
    """La entrada se cerró antes de completar el menú."""


@dataclass(frozen=True, slots=True)
class Patient:
    """Registro de un ingreso: nombre, nivel 1–3 y momento de llegada."""

    name: str
    triage_level: int
    arrived_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise TypeError("name debe ser str.")
        cleaned = self.name.strip()
        if cleaned == "":
            raise ValueError("el nombre no puede estar vacío.")
        if cleaned != self.name:
            object.__setattr__(self, "name", cleaned)
        if type(self.triage_level) is not int:
            raise TypeError("triage_level debe ser un entero 1, 2 o 3.")
        if self.triage_level not in TRIAGE_LEVELS:
            raise ValueError("triage_level debe ser 1, 2 o 3.")
        if not isinstance(self.arrived_at, datetime):
            raise TypeError("arrived_at debe ser datetime.")

    @classmethod
    def at_arrival(
        cls,
        name: str,
        triage_level: int,
        arrived_at: datetime | None = None,
    ) -> Patient:
        """Crea el registro. Sin timestamp, usa la hora UTC de este instante."""
        when = datetime.now(timezone.utc) if arrived_at is None else arrived_at
        return cls(name, triage_level, when)


class _Spot(NamedTuple):
    arrived_at: datetime
    sequence: int
    patient: Patient


class TriageQueue:
    """Tres colas, una por nivel. El nivel 1 se atiende antes que el 2 y el 3.

    Dentro de un nivel la clave es (arrived_at, secuencia de registro).
    La secuencia desempata dos llegadas con el mismo timestamp y deja el
    orden estable. Un lock cubre cada operación para que dos workers no
    extraigan al mismo paciente.
    """

    def __init__(self) -> None:
        self._buckets: dict[int, deque[_Spot]] = {
            level: deque() for level in TRIAGE_LEVELS
        }
        self._sequence = 0
        self._lock = threading.RLock()

    def enqueue(self, patient: Patient) -> None:
        """Inserta al paciente en su nivel, por hora de llegada."""
        if not isinstance(patient, Patient):
            raise TypeError("enqueue espera un Patient.")
        with self._lock:
            sequence = self._sequence
            self._sequence += 1
            bucket = self._buckets[patient.triage_level]
            spot = _Spot(patient.arrived_at, sequence, patient)
            index = self._insertion_index(bucket, spot)
            if index == len(bucket):
                bucket.append(spot)
            else:
                bucket.insert(index, spot)

    def dequeue(self) -> Patient:
        """Extrae al siguiente paciente. Falla con EmptyQueueError si no hay nadie."""
        with self._lock:
            bucket = self._first_bucket()
            if bucket is None:
                raise EmptyQueueError(EMPTY_DEQUEUE_MESSAGE)
            return bucket.popleft().patient

    def peek(self) -> Patient:
        """Devuelve al siguiente paciente sin extraerlo."""
        with self._lock:
            bucket = self._first_bucket()
            if bucket is None:
                raise EmptyQueueError(EMPTY_PEEK_MESSAGE)
            return bucket[0].patient

    def list_queue(self) -> list[Patient]:
        """Copia de quienes esperan, en el orden en que serán atendidos."""
        with self._lock:
            return [
                spot.patient
                for level in TRIAGE_LEVELS
                for spot in self._buckets[level]
            ]

    def stats(self) -> dict[int, int]:
        """Conteo de quienes esperan. Las claves son 1, 2 y 3, aunque valgan 0."""
        with self._lock:
            return {level: len(self._buckets[level]) for level in TRIAGE_LEVELS}

    def _first_bucket(self) -> deque[_Spot] | None:
        for level in TRIAGE_LEVELS:
            bucket = self._buckets[level]
            if bucket:
                return bucket
        return None

    def _insertion_index(self, bucket: deque[_Spot], spot: _Spot) -> int:
        index = len(bucket)
        while index > 0:
            previous = bucket[index - 1]
            try:
                is_after_previous = (previous.arrived_at, previous.sequence) <= (
                    spot.arrived_at,
                    spot.sequence,
                )
            except TypeError as exc:
                raise TypeError(
                    "arrived_at debe poder compararse con las llegadas ya "
                    "registradas en ese nivel."
                ) from exc
            if is_after_previous:
                break
            index -= 1
        return index


def format_patient(patient: Patient) -> str:
    label = LEVEL_LABEL[patient.triage_level]
    stamp = patient.arrived_at.isoformat(timespec="seconds")
    return f"{patient.name} — nivel {patient.triage_level} ({label}) — llegada {stamp}"


def render_example() -> str:
    """Ejemplo fijo. Lo calcula TriageQueue; no usa la cola de la sesión."""
    queue = TriageQueue()
    registered: list[Patient] = []
    for name, level, arrived_at in DEMO_ARRIVALS:
        patient = Patient(name, level, arrived_at)
        queue.enqueue(patient)
        registered.append(patient)
    lines = [
        "Ejemplo de prioridad",
        "Este ejemplo no modifica la cola actual.",
        "",
        "Registro, en este orden:",
    ]
    lines.extend(
        f"{index}. {format_patient(patient)}"
        for index, patient in enumerate(registered, start=1)
    )
    lines.append("")
    lines.append("Orden de atención:")
    lines.extend(
        f"{index}. {format_patient(patient)}"
        for index, patient in enumerate(queue.list_queue(), start=1)
    )
    lines.append("")
    lines.append(
        "Marta llegó la tercera y se atiende la primera: el nivel 1 pasa "
        "por delante del 2 y del 3."
    )
    lines.append(
        "Luis se atiende antes que Nora: los dos son nivel 2 y Luis llegó antes."
    )
    return "\n".join(lines)


def render_help() -> str:
    return "\n".join(
        (
            "Uso: python3 triage_queue.py [--help | --demo]",
            "",
            "Sin argumentos abre el menú.",
            "  --help   muestra esta ayuda y el ejemplo de prioridad",
            "  --demo   imprime el ejemplo calculado con la cola",
            "",
            "Menú: 1 registrar, 2 llamar al siguiente, 3 ver quién sigue,",
            "4 ver la cola, 5 ver conteos, 6 ver el ejemplo, 0 salir.",
            "",
            render_example(),
        )
    )


class TriageCLI:
    """Menú de texto. Toda la entrada y la salida pasan por aquí."""

    def __init__(
        self,
        queue: TriageQueue | None = None,
        input_fn: Callable[[], str] | None = None,
        output_fn: Callable[[str], None] | None = None,
        echo: bool = False,
    ) -> None:
        self.queue = TriageQueue() if queue is None else queue
        self._input = input if input_fn is None else input_fn
        self._output = print if output_fn is None else output_fn
        self._echo = echo

    @classmethod
    def from_stdio(cls) -> TriageCLI:
        # En un tubo la entrada no se ve; se repite con prefijo para la transcripción.
        # En una terminal el eco del propio terminal basta.
        return cls(echo=not sys.stdin.isatty())

    def run(self) -> int:
        try:
            self._write(self._header())
            while True:
                self._write(self._status_line())
                self._write(self._short_menu())
                try:
                    choice = self._read("Opción:")
                except _InputClosed:
                    self._write("Entrada cerrada. Sesión terminada.")
                    return 0
                if choice == "0":
                    self._write("Sesión cerrada.")
                    return 0
                handler = {
                    "1": self._register,
                    "2": self._call_next,
                    "3": self._show_next,
                    "4": self._show_queue,
                    "5": self._show_stats,
                    "6": self._show_example,
                }.get(choice)
                if handler is None:
                    self._write(
                        f'Opción no reconocida: "{choice}". '
                        "Escribe 1, 2, 3, 4, 5, 6 o 0."
                    )
                    continue
                try:
                    handler()
                except _InputClosed:
                    self._write("Entrada cerrada. Sesión terminada.")
                    return 0
        except KeyboardInterrupt:
            self._write("Interrupción. Sesión terminada.")
            return 0

    def _header(self) -> str:
        return "\n".join(
            (
                "Gestor de cola de triaje",
                "",
                "Se atiende primero el nivel 1 (crítico), después el 2 (urgente)",
                "y al final el 3 (estándar). Dentro de un nivel, manda la hora de",
                "llegada; si la hora coincide, manda el orden de registro.",
                "",
                "1  Registrar paciente",
                "2  Llamar al siguiente",
                "3  Ver quién sigue, sin retirarlo",
                "4  Ver la cola",
                "5  Ver conteos por nivel",
                "6  Ver un ejemplo de prioridad",
                "0  Salir",
            )
        )

    def _short_menu(self) -> str:
        return "\n".join(
            (
                "1 registrar    2 llamar    3 ver siguiente",
                "4 ver cola     5 conteos   6 ejemplo     0 salir",
            )
        )

    def _status_line(self) -> str:
        total = sum(self.queue.stats().values())
        if total == 0:
            return "En espera: 0."
        nxt = self.queue.peek()
        return (
            f"En espera: {total}. Siguiente: {nxt.name} (nivel {nxt.triage_level})."
        )

    def _register(self) -> None:
        name = self._ask_name()
        level = self._ask_level()
        patient = Patient.at_arrival(name, level)
        self.queue.enqueue(patient)
        waiting = self.queue.list_queue()
        position = next(
            index for index, item in enumerate(waiting, start=1) if item is patient
        )
        self._write(f"Registrado: {format_patient(patient)}.")
        self._write(f"Lugar en la atención: {position} de {len(waiting)}.")

    def _ask_name(self) -> str:
        while True:
            raw = self._read("Nombre del paciente:")
            if raw == "":
                self._write("El nombre no puede estar vacío. Escríbelo de nuevo.")
                continue
            return raw

    def _ask_level(self) -> int:
        while True:
            raw = self._read("Nivel de triaje (1 crítico, 2 urgente, 3 estándar):")
            if raw in {"1", "2", "3"}:
                return int(raw)
            self._write(
                f'Nivel no válido: "{raw}". '
                "Escribe 1 (crítico), 2 (urgente) o 3 (estándar)."
            )

    def _call_next(self) -> None:
        try:
            patient = self.queue.dequeue()
        except EmptyQueueError as exc:
            self._write(str(exc))
            self._write("Siguiente paso: opción 1 para registrar una llegada.")
            return
        remaining = sum(self.queue.stats().values())
        self._write(f"Llamado: {format_patient(patient)}.")
        self._write(f"Quedan en espera: {remaining}.")

    def _show_next(self) -> None:
        try:
            patient = self.queue.peek()
        except EmptyQueueError as exc:
            self._write(str(exc))
            self._write("Siguiente paso: opción 1 para registrar una llegada.")
            return
        self._write(f"Sigue {format_patient(patient)}.")
        self._write("No se retira de la cola.")

    def _show_queue(self) -> None:
        patients = self.queue.list_queue()
        if not patients:
            self._write("Cola vacía. No hay pacientes en espera.")
            self._write("Siguiente paso: opción 1 para registrar una llegada.")
            return
        self._write(
            f"Cola de atención ({len(patients)}). "
            f"Siguiente: {format_patient(patients[0])}."
        )
        for index, patient in enumerate(patients, start=1):
            self._write(f"{index}. {format_patient(patient)}")

    def _show_stats(self) -> None:
        counts = self.queue.stats()
        self._write("Conteos por nivel")
        for level in TRIAGE_LEVELS:
            self._write(f"nivel {level} ({LEVEL_LABEL[level]}): {counts[level]}")
        self._write(f"total: {sum(counts.values())}")

    def _show_example(self) -> None:
        self._write(render_example())

    def _read(self, prompt: str) -> str:
        self._write(prompt)
        try:
            value = self._input()
        except EOFError as exc:
            raise _InputClosed from exc
        if not isinstance(value, str):
            raise _InputClosed
        if self._echo:
            self._write(f"> {value}")
        return value.strip()

    def _write(self, message: str) -> None:
        self._output(message)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--help"] or args == ["-h"] or args == ["--ayuda"]:
        print(render_help())
        return 0
    if args == ["--demo"]:
        print(render_example())
        return 0
    if args:
        print(f"Argumento no reconocido: {' '.join(args)}. Usa --help.")
        return 2
    return TriageCLI.from_stdio().run()


if __name__ == "__main__":
    raise SystemExit(main())
