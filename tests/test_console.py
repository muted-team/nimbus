"""Russian diagnostic output must not break Windows HTTP handlers."""
import io
import unittest

from modules.console import configure_console


class ConsoleTests(unittest.TestCase):
    def test_legacy_windows_stream_accepts_russian_text(self):
        output = io.BytesIO()
        stream = io.TextIOWrapper(output, encoding="cp1252", newline="\n")
        configure_console([stream])
        stream.write("Добавлено фото в папку\n")
        stream.flush()
        self.assertEqual(output.getvalue().decode("utf-8"), "Добавлено фото в папку\n")

    def test_captured_or_unavailable_streams_are_supported(self):
        captured = io.StringIO()
        configure_console([captured, None])
        captured.write("Проверка")
        self.assertEqual(captured.getvalue(), "Проверка")


if __name__ == "__main__":
    unittest.main()
