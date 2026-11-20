"""Start the API (uvicorn with --reload) and the import worker together.

  python -m scripts.run_api

Ctrl+C stops both.
"""

import subprocess
import sys


def main() -> None:
    processes = [
        subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--reload"]),
        subprocess.Popen([sys.executable, "-m", "app.worker"]),
    ]
    try:
        for process in processes:
            process.wait()
    except KeyboardInterrupt:
        # Ctrl+C reaches both processes too; wait for them to shut down.
        for process in processes:
            process.wait()


if __name__ == "__main__":
    main()
