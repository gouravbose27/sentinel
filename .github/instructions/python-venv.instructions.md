---
description: "Use when installing, upgrading, or removing Python packages/modules, running pip, or setting up dependencies. Enforces installing into a virtual environment, never globally."
---
# Python package installation

- Always install packages into a virtual environment, never the global/system interpreter.
- Look for an existing venv first (`.venv/`, `venv/`, `env/`). If none exists, create one at the workspace root: `python -m venv .venv`.
- Use the venv's interpreter explicitly rather than relying on activation:
  - Windows: `.venv\Scripts\python.exe -m pip install <package>`
  - macOS/Linux: `.venv/bin/python -m pip install <package>`
- Never run bare `pip install`, `pip install --user`, or `--break-system-packages`.
- Record dependencies in `requirements.txt` (or `pyproject.toml` if the project uses it) when adding a package.
- Install from the file with `.venv\Scripts\python.exe -m pip install -r requirements.txt`.
- Keep `.venv/` out of version control by listing it in `.gitignore`.
- If the Python environment tools are available, make sure the selected interpreter is the venv before installing.
