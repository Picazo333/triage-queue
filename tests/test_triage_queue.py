"""Pruebas del modelo, del menú y del punto de entrada."""

from __future__ import annotations

import ast
import subprocess
import sys
import threading
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from triage_queue import (  # noqa: E402
    EMPTY_DEQUEUE_MESSAGE,
    EMPTY_PEEK_MESSAGE,
    EmptyQueueError,
    Patient,
    TriageCLI,
    TriageQueue,
    main,
    render_example,
)

LEVELS = (1, 2, 3)

SCRIPT = ROOT / "triage_queue.py"
UTC = timezone.utc


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 11, 6, hour, minute, second, tzinfo=UTC)


def feed(script: str, echo: bool = True) -> str:
    lines = iter(script.splitlines())

    def reader() -> str:
        try:
            return next(lines)
        except StopIteration as exc:
            raise EOFError from exc

    chunks: list[str] = []
    code = TriageCLI(input_fn=reader, output_fn=chunks.append, echo=echo).run()
    if code != 0:
        raise AssertionError(f"la sesión terminó con código {code}")
    return "\n".join(chunks)


def called_names(output: str) -> list[str]:
    names = []
    for line in output.splitlines():
        if line.startswith("Llamado: "):
            names.append(line.removeprefix("Llamado: ").split(" — ", maxsplit=1)[0])
    return names


class PatientTests(unittest.TestCase):
    def test_records_name_level_and_arrival(self) -> None:
        moment = at(9, 30)
        patient = Patient("  Ana  ", 1, moment)
        self.assertEqual(patient.name, "Ana")
        self.assertEqual(patient.triage_level, 1)
        self.assertEqual(patient.arrived_at, moment)
        stamped = Patient.at_arrival("Luis", 2)
        self.assertEqual(stamped.triage_level, 2)
        self.assertIsNotNone(stamped.arrived_at.tzinfo)

    def test_rejects_blank_name_bad_level_and_bad_timestamp(self) -> None:
        moment = at(9)
        with self.assertRaises(ValueError):
            Patient("   ", 1, moment)
        with self.assertRaises(TypeError):
            Patient(12, 1, moment)  # type: ignore[arg-type]
        for bad in (True, False, 0, 4, "1"):
            with self.assertRaises((TypeError, ValueError)):
                Patient("Ana", bad, moment)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            Patient("Ana", 1, "hoy")  # type: ignore[arg-type]


class QueueOrderTests(unittest.TestCase):
    def test_priority_beats_an_earlier_arrival(self) -> None:
        queue = TriageQueue()
        standard = Patient("Ana", 3, at(8))
        critical = Patient("Marta", 1, at(18))
        queue.enqueue(standard)
        queue.enqueue(critical)
        self.assertIs(queue.dequeue(), critical)
        self.assertIs(queue.dequeue(), standard)

    def test_same_level_uses_arrival_timestamp(self) -> None:
        queue = TriageQueue()
        later = Patient("Ana", 2, at(11))
        earlier = Patient("Bea", 2, at(9))
        queue.enqueue(later)
        queue.enqueue(earlier)
        self.assertEqual([item.name for item in queue.list_queue()], ["Bea", "Ana"])

    def test_equal_timestamp_keeps_registration_order(self) -> None:
        moment = at(10, 0, 0)
        queue = TriageQueue()
        first = Patient("Ana", 2, moment)
        second = Patient("Ana", 2, moment)
        queue.enqueue(first)
        queue.enqueue(second)
        self.assertIs(queue.dequeue(), first)
        self.assertIs(queue.dequeue(), second)

    def test_critical_patient_jumps_ahead_of_lower_levels(self) -> None:
        queue = TriageQueue()
        luis = Patient("Luis", 2, at(10, 1))
        ana = Patient("Ana", 3, at(10, 0))
        nora = Patient("Nora", 2, at(10, 3))
        queue.enqueue(ana)
        queue.enqueue(luis)
        queue.enqueue(nora)
        marta = Patient("Marta", 1, at(10, 2))
        queue.enqueue(marta)
        self.assertEqual(
            [item.name for item in queue.list_queue()],
            ["Marta", "Luis", "Nora", "Ana"],
        )
        self.assertEqual(queue.stats(), {1: 1, 2: 2, 3: 1})

    def test_level_order_with_several_patients_each(self) -> None:
        queue = TriageQueue()
        patients = [
            Patient("A3", 3, at(8, 1)),
            Patient("B3", 3, at(8, 2)),
            Patient("C1", 1, at(9, 5)),
            Patient("D2", 2, at(8, 4)),
            Patient("E1", 1, at(9, 1)),
            Patient("F2", 2, at(8, 6)),
        ]
        for patient in patients:
            queue.enqueue(patient)
        # E1 llegó antes que C1 dentro del nivel 1. El resto sigue el nivel.
        self.assertEqual(
            [item.name for item in queue.list_queue()],
            ["E1", "C1", "D2", "F2", "A3", "B3"],
        )


class QueueOperationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.queue = TriageQueue()
        self.patient = Patient("Ana", 2, at(10))
        self.queue.enqueue(self.patient)

    def test_peek_does_not_remove(self) -> None:
        self.assertIs(self.queue.peek(), self.patient)
        self.assertIs(self.queue.peek(), self.patient)
        self.assertEqual(self.queue.stats(), {1: 0, 2: 1, 3: 0})

    def test_dequeue_then_empty_errors(self) -> None:
        self.assertIs(self.queue.dequeue(), self.patient)
        with self.assertRaises(EmptyQueueError) as dequeue_error:
            self.queue.dequeue()
        with self.assertRaises(EmptyQueueError) as peek_error:
            self.queue.peek()
        self.assertEqual(str(dequeue_error.exception), EMPTY_DEQUEUE_MESSAGE)
        self.assertEqual(str(peek_error.exception), EMPTY_PEEK_MESSAGE)
        self.assertEqual(self.queue.list_queue(), [])
        self.assertEqual(self.queue.stats(), {1: 0, 2: 0, 3: 0})

    def test_list_queue_is_a_snapshot(self) -> None:
        listed = self.queue.list_queue()
        self.assertIsInstance(listed, list)
        self.queue.dequeue()
        self.assertEqual(listed, [self.patient])
        listed.append(Patient("Otra", 1, at(11)))
        self.assertEqual(self.queue.list_queue(), [])

    def test_enqueue_rejects_non_patient_and_mixed_clocks(self) -> None:
        with self.assertRaises(TypeError):
            self.queue.enqueue("Ana")  # type: ignore[arg-type]
        naive = Patient("Bea", 2, datetime(2026, 11, 6, 12, 0, 0))
        with self.assertRaises(TypeError):
            self.queue.enqueue(naive)

    def test_stats_follow_dequeue(self) -> None:
        self.queue.enqueue(Patient("Bea", 1, at(11)))
        self.queue.dequeue()
        self.assertEqual(self.queue.stats(), {1: 0, 2: 1, 3: 0})


class CliTests(unittest.TestCase):
    def test_session_respects_priority_and_arrival(self) -> None:
        output = feed(
            "\n".join(
                [
                    "1",
                    "Ana",
                    "3",
                    "1",
                    "Luis",
                    "2",
                    "1",
                    "Marta",
                    "1",
                    "1",
                    "Nora",
                    "2",
                    "4",
                    "5",
                    "3",
                    "2",
                    "2",
                    "2",
                    "2",
                    "2",
                    "0",
                ]
            )
        )
        self.assertNotIn("Traceback", output)
        self.assertEqual(called_names(output), ["Marta", "Luis", "Nora", "Ana"])
        places = [
            line
            for line in output.splitlines()
            if line.startswith("Lugar en la atención:")
        ]
        self.assertEqual(
            places,
            [
                "Lugar en la atención: 1 de 1.",
                "Lugar en la atención: 1 de 2.",
                "Lugar en la atención: 1 de 3.",
                "Lugar en la atención: 3 de 4.",
            ],
        )
        self.assertIn("Cola de atención (4).", output)
        self.assertIn("nivel 1 (crítico): 1", output)
        self.assertIn("No se retira de la cola.", output)
        self.assertIn(EMPTY_DEQUEUE_MESSAGE, output)
        self.assertIn("Sesión cerrada.", output)
        queue_block = output.split("Cola de atención (4).", maxsplit=1)[1]
        queue_block = queue_block.split("Conteos por nivel", maxsplit=1)[0]
        self.assertLess(queue_block.index("1. Marta"), queue_block.index("2. Luis"))
        self.assertLess(queue_block.index("2. Luis"), queue_block.index("3. Nora"))
        self.assertLess(queue_block.index("3. Nora"), queue_block.index("4. Ana"))

    def test_invalid_input_and_empty_queue_keep_the_loop(self) -> None:
        output = feed(
            "\n".join(
                [
                    "foo",
                    "",
                    "2",
                    "3",
                    "4",
                    "1",
                    "",
                    "   ",
                    "Zoe",
                    "9",
                    "cero",
                    "1",
                    "2",
                    "0",
                ]
            )
        )
        self.assertNotIn("Traceback", output)
        self.assertIn('Opción no reconocida: "foo".', output)
        self.assertIn('Opción no reconocida: "".', output)
        self.assertIn(EMPTY_DEQUEUE_MESSAGE, output)
        self.assertIn(EMPTY_PEEK_MESSAGE, output)
        self.assertIn("Cola vacía. No hay pacientes en espera.", output)
        self.assertIn("Siguiente paso: opción 1 para registrar una llegada.", output)
        self.assertIn("El nombre no puede estar vacío.", output)
        self.assertIn('Nivel no válido: "9".', output)
        self.assertIn('Nivel no válido: "cero".', output)
        self.assertEqual(called_names(output), ["Zoe"])

    def test_example_does_not_replace_the_live_queue(self) -> None:
        output = feed("\n".join(["1", "Zoe", "3", "6", "4", "0"]))
        self.assertIn("Este ejemplo no modifica la cola actual.", output)
        self.assertIn("Marta llegó la tercera", output)
        self.assertIn("Registrado: Zoe — nivel 3", output)
        self.assertIn("Cola de atención (1). Siguiente: Zoe — nivel 3", output)

    def test_keyboard_interrupt_ends_cleanly(self) -> None:
        def reader() -> str:
            raise KeyboardInterrupt

        chunks: list[str] = []
        code = TriageCLI(input_fn=reader, output_fn=chunks.append).run()
        self.assertEqual(code, 0)
        self.assertIn("Interrupción. Sesión terminada.", "\n".join(chunks))

    def test_help_demo_and_unknown_argument(self) -> None:
        captured = StringIO()
        with redirect_stdout(captured):
            self.assertEqual(main(["--help"]), 0)
            self.assertEqual(main(["--demo"]), 0)
            self.assertEqual(main(["--ayuda"]), 0)
            self.assertEqual(main(["--no-existe"]), 2)
        text = captured.getvalue()
        self.assertIn("Argumento no reconocido: --no-existe.", text)
        attention = text.split("Orden de atención:", maxsplit=1)[1]
        self.assertLess(attention.index("1. Marta"), attention.index("2. Luis"))
        self.assertLess(attention.index("2. Luis"), attention.index("3. Nora"))
        self.assertLess(attention.index("3. Nora"), attention.index("4. Ana"))


class EntrypointTests(unittest.TestCase):
    def test_demo_matches_readme(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--demo"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, render_example() + "\n")
        self.assertNotIn("Traceback", result.stderr)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(result.stdout.strip(), readme)
        self.assertIn(EMPTY_DEQUEUE_MESSAGE, readme)

    def test_piped_session_echoes_input_and_exits_zero(self) -> None:
        script = "\n".join(["1", "Ana", "3", "4", "2", "0"]) + "\n"
        result = subprocess.run(
            [sys.executable, "-u", str(SCRIPT)],
            input=script,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("> Ana", result.stdout)
        self.assertIn("> 3", result.stdout)
        self.assertIn("Llamado: Ana — nivel 3", result.stdout)
        self.assertNotIn("Traceback", result.stderr + result.stdout)

    def test_only_stdlib_imports(self) -> None:
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules.add(node.module.split(".", maxsplit=1)[0])
        allowed = {
            "__future__",
            "collections",
            "dataclasses",
            "datetime",
            "sys",
            "threading",
            "typing",
        }
        self.assertLessEqual(modules, allowed)


class ConcurrencyTests(unittest.TestCase):
    def test_four_consumers_claim_each_patient_once(self) -> None:
        for _ in range(20):
            queue = TriageQueue()
            patients = [
                Patient(f"P{index}", (index % 3) + 1, at(8) + timedelta(seconds=index))
                for index in range(120)
            ]
            for patient in patients:
                queue.enqueue(patient)
            claimed: list[Patient] = []
            guard = threading.Lock()

            def consume() -> None:
                while True:
                    try:
                        patient = queue.dequeue()
                    except EmptyQueueError:
                        return
                    with guard:
                        claimed.append(patient)

            threads = [threading.Thread(target=consume) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertCountEqual(claimed, patients)
            self.assertEqual(len({id(item) for item in claimed}), len(patients))
            self.assertEqual(queue.stats(), {1: 0, 2: 0, 3: 0})

    def test_producer_and_consumer_keep_level_order(self) -> None:
        queue = TriageQueue()
        produced = [
            Patient(f"L{level}-{index}", level, at(8) + timedelta(seconds=index))
            for index in range(40)
            for level in LEVELS
        ]
        claimed: list[Patient] = []
        done = threading.Event()
        start = threading.Barrier(2)

        def produce() -> None:
            start.wait()
            for patient in produced:
                queue.enqueue(patient)
            done.set()

        def consume() -> None:
            start.wait()
            while True:
                try:
                    claimed.append(queue.dequeue())
                except EmptyQueueError:
                    if not done.is_set():
                        continue
                    try:
                        claimed.append(queue.dequeue())
                    except EmptyQueueError:
                        return

        workers = (
            threading.Thread(target=produce),
            threading.Thread(target=consume),
        )
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertCountEqual(claimed, produced)
        for level in (1, 2, 3):
            expected = [item.name for item in produced if item.triage_level == level]
            actual = [item.name for item in claimed if item.triage_level == level]
            self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
