"""Copy only browser assets to the public deployment directory."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parent
output = root / "public"
output.mkdir(exist_ok=True)
for name in ("index.html", "styles.css", "home.js", "shared.js", "pile-physics.js"):
    shutil.copy2(root / name, output / name)
for name in ("assets", "vendor"):
    shutil.copytree(root / name, output / name, dirs_exist_ok=True)
