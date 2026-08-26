"""
Run this script INSIDE your activated venv to verify the environment.

  Windows:  venv\Scripts\activate  →  python check_env.py
  Mac/Linux: source venv/bin/activate  →  python check_env.py
"""

import sys
import subprocess

print("=" * 50)
print("  Environment Diagnostic")
print("=" * 50)
print(f"\nPython: {sys.version}")
print(f"Executable: {sys.executable}\n")

REQUIRED = {
    "numpy":      ("2.1.0",  "numpy"),
    "pandas":     ("2.2.3",  "pandas"),
    "nltk":       ("3.8.0",  "nltk"),
    "sklearn":    ("1.5.2",  "scikit-learn"),
    "seaborn":    ("0.12.0", "seaborn"),
    "matplotlib": ("3.7.0",  "matplotlib"),
    "jupyter":    ("1.0.0",  "jupyter"),
    "ipykernel":  ("6.0.0",  "ipykernel"),
}

all_ok = True
for module, (min_ver, pip_name) in REQUIRED.items():
    try:
        mod = __import__(module)
        ver = getattr(mod, "__version__", "unknown")
        print(f"  ✓  {pip_name:<20} {ver}")
    except ImportError:
        print(f"  ✗  {pip_name:<20} MISSING")
        all_ok = False

print()
if all_ok:
    print("✅  All packages present. If the notebook is still stuck,")
    print("   make sure VS Code is using THIS venv as the kernel.")
    print("   Click the kernel selector (top right of notebook) →")
    print("   'Select Another Kernel' → 'Python Environments' →")
    print("   choose the venv Python.")
else:
    print("❌  Some packages are missing. Run inside the venv:")
    print("   pip install -r requirements.txt")

print("=" * 50)
