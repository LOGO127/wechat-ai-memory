from pathlib import Path
import subprocess
import sys


project_dir = Path(__file__).resolve().parent
project_python = project_dir / ".venv-gui" / "Scripts" / "python.exe"
if project_python.is_file() and Path(sys.executable).resolve() != project_python.resolve():
    raise SystemExit(
        subprocess.call(
            [str(project_python), str(Path(__file__).resolve()), *sys.argv[1:]],
            cwd=project_dir,
        )
    )

src_dir = project_dir / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

if __name__ == "__main__":
    if sys.argv[1:2] == ["--verify-runtime"]:
        from wechat_context_exporter.runtime_check import main

        raise SystemExit(main(sys.argv[2:]))
    else:
        from wechat_context_exporter.ui.main_window import main

        raise SystemExit(main())
