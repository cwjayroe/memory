from __future__ import annotations

import subprocess
import sys


def test_examples_import_is_safe_without_running_examples():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import examples; print('examples import ok')",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "examples import ok"


def test_ingest_help_works_without_mem0_runtime():
    result = subprocess.run(
        [sys.executable, "ingest.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Project memory ingestion CLI" in result.stdout
