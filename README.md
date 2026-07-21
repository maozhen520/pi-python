# pi-python

Python implementation aligned with [earendil-works/pi](https://github.com/earendil-works/pi) semantics: thin LLM adapter, agent runtime, Textual TUI, and interactive coding CLI (`piy`).

## Workspace

```text
packages/
  pi_llm/           # Thin LiteLLM adapter
  pi_agent/         # Agent loop + Agent SDK
  pi_tui/           # Textual widgets/layouts
  pi_coding_agent/  # Coding CLI (piy) wiring
```

## Develop

```bash
# Optional: faster installs in CN (do not commit as default — CI uses public PyPI)
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

uv sync --group dev
uv run pytest
uv run ruff check .
uv run ty check
```

## CLI

```bash
uv run piy
```
