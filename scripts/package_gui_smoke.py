from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from pypdf import PdfReader
from pywinauto import Desktop
from pywinauto.application import Application


def _wait_for(predicate, description: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for {description}")


def _text_names(window) -> set[str]:
    return {
        item.element_info.name
        for item in window.descendants(control_type="Text")
        if item.element_info.name
    }


def _ensure_checked(checkbox) -> None:
    if checkbox.get_toggle_state() == 0:
        checkbox.toggle()


def run_smoke(executable: Path, fixture: Path, output: Path) -> dict[str, object]:
    executable = executable.resolve(strict=True)
    fixture = fixture.resolve(strict=True)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    for path in (output, output.with_suffix(".md"), output.with_suffix(".json")):
        path.unlink(missing_ok=True)

    desktop = Desktop(backend="uia")
    existing_windows = {item.handle for item in desktop.windows()}
    app = Application(backend="uia").start(str(executable), work_dir=str(output.parent))
    window = None
    window_handle = None
    try:
        def find_main_window() -> bool:
            nonlocal window_handle
            for item in desktop.windows():
                if item.handle in existing_windows:
                    continue
                if item.element_info.automation_id == "QApplication.MainWindow" and item.is_visible():
                    window_handle = item.handle
                    return True
            return False

        _wait_for(find_main_window, "new application window", timeout=45)
        assert window_handle is not None
        attached_app = Application(backend="uia").connect(handle=window_handle)
        window = attached_app.window(handle=window_handle)
        window.wait("visible ready", timeout=15)

        source_combo = sorted(
            window.descendants(control_type="ComboBox"),
            key=lambda item: item.rectangle().top,
        )[0]
        source_combo.select("JSON 文件")
        time.sleep(0.5)

        source_edit = window.child_window(
            auto_id="QApplication.MainWindow.appRoot.mainSplitter.sidebar.sourcePathField",
            control_type="Edit",
        )
        output_edit = window.child_window(
            auto_id="QApplication.MainWindow.appRoot.mainSplitter.sidebar.outputPathField",
            control_type="Edit",
        )
        source_edit.set_edit_text(str(fixture))
        window.child_window(title="加载", control_type="Button").invoke()
        _wait_for(lambda: "消息读取完成" in _text_names(window), "message loading")

        search = window.child_window(
            auto_id="QApplication.MainWindow.appRoot.mainSplitter.workspace.searchField",
            control_type="Edit",
        )
        search.set_edit_text("随机种子")
        _wait_for(
            lambda: "1 条匹配 · 当前范围 8 条" in _text_names(window),
            "search filtering",
        )

        output_edit.set_edit_text(str(output))
        _ensure_checked(window.child_window(title="保留渲染 PNG", control_type="CheckBox"))
        _ensure_checked(window.child_window(title="生成 Markdown 与 JSON", control_type="CheckBox"))
        window.child_window(title="生成记忆档案", control_type="Button").invoke()

        _wait_for(output.is_file, "PDF output", timeout=45)
        _wait_for(output.with_suffix(".json").is_file, "JSON output", timeout=15)
        _wait_for(output.with_suffix(".md").is_file, "Markdown output", timeout=15)

        # Qt dialog titles are not always exposed consistently by Windows UIA.
        dialogs = [
            item
            for item in desktop.windows()
            if item.process_id() == window.process_id()
            and item.handle != window.handle
            and item.is_visible()
        ]
        if dialogs:
            buttons = dialogs[-1].descendants(control_type="Button")
            if buttons:
                buttons[-1].click_input()
            else:
                dialogs[-1].type_keys("{ENTER}")

        document = PdfReader(output)
        payload = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
        messages = payload["conversations"][0]["messages"]
        pages_dir = output.with_name(f"{output.stem}_pages")
        rendered_pages = sorted(pages_dir.glob("page_*.png"))
        result: dict[str, object] = {
            "executable": executable.name,
            "pdf_pages": len(document.pages),
            "messages": len(messages),
            "message_id": messages[0]["id"],
            "markdown_bytes": output.with_suffix(".md").stat().st_size,
            "rendered_pages": len(rendered_pages),
        }
        if result["pdf_pages"] != 1 or result["messages"] != 1 or result["message_id"] != "m006":
            raise RuntimeError(f"Unexpected packaged export result: {result}")
        if result["rendered_pages"] != 1:
            raise RuntimeError(f"Expected one rendered page: {result}")
        return result
    finally:
        if window is not None:
            try:
                Application(backend="uia").connect(process=window.process_id()).kill(soft=False)
            except Exception:
                pass
        try:
            app.kill(soft=False)
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Exercise a packaged Windows GUI export.")
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_smoke(args.exe, args.fixture, args.output), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
