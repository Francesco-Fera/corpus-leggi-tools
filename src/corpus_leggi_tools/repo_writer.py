"""Scrittura atomica dei file nel dataset con manifest SHA-256 per dedup.

Il manifest è un ``{path_relativo: sha256_hex}`` persistente in
``<dataset_root>/data/manifest.json``. ``write_if_changed`` evita scritture
quando il contenuto non è variato — condizione chiave per delta sync efficiente.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

MANIFEST_REL_PATH = "data/manifest.json"


def sha256_of(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class RepoWriter:
    """Writer stateful per un singolo dataset root.

    Tipico uso::

        w = RepoWriter(Path("../corpus-leggi"))
        w.write_if_changed("leggi/legge/2024/legge_.../art-1.md", md)
        ...
        w.save_manifest()
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self._manifest_path = root / MANIFEST_REL_PATH
        self.manifest: dict[str, str] = self._load_manifest()
        self._changed = 0
        self._written = 0
        self._skipped = 0

    def _load_manifest(self) -> dict[str, str]:
        if not self._manifest_path.exists():
            return {}
        data = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Manifest {self._manifest_path} non è un oggetto JSON")
        return {str(k): str(v) for k, v in data.items()}

    def write_if_changed(self, relative_path: str, content: str) -> bool:
        """Scrive il file solo se il contenuto è cambiato. Ritorna True se scritto."""
        new_hash = sha256_of(content)
        if self.manifest.get(relative_path) == new_hash:
            self._skipped += 1
            return False
        full_path = self.root / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        self.manifest[relative_path] = new_hash
        self._written += 1
        self._changed += 1
        return True

    def save_manifest(self) -> None:
        self._manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self._manifest_path.write_text(
            json.dumps(self.manifest, indent=2, sort_keys=True, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )

    @property
    def stats(self) -> dict[str, int]:
        return {"written": self._written, "skipped": self._skipped}
