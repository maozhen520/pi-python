"""Shared Textual theme — aligned with upstream pi: conversation-first, minimal chrome."""

APP_CSS = """
Screen {
    background: #0c0c0e;
}

#layout-main {
    height: 1fr;
    padding: 0 1;
}

TranscriptView {
    height: 1fr;
    min-height: 6;
    background: #0c0c0e;
    border: none;
    overflow-y: auto;
    padding: 0 0 1 0;
    color: #d4d4d8;
}

EditorWidget {
    height: 5;
    min-height: 4;
    border: tall #27272a;
    border-title-color: #a1a1aa;
    border-title-style: bold;
    background: #141416;
    margin: 0 0 1 0;
}

EditorWidget:focus-within {
    border: tall #3f3f46;
    border-title-color: #e4e4e7;
}
"""
