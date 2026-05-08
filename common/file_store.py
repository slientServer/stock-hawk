import json
from datetime import date, datetime
from pathlib import Path


class FileStore:
    def __init__(self, base_dir: str = "data/files"):
        self.base_dir = Path(base_dir)

    def _get_dir(self, file_type: str, target_date: date | None = None) -> Path:
        if target_date is None:
            target_date = date.today()
        dir_path = self.base_dir / file_type / str(target_date.year) / f"{target_date.month:02d}" / f"{target_date.day:02d}"
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path

    def _meta_path(self, file_path: Path) -> Path:
        return file_path.with_suffix(file_path.suffix + ".meta.json")

    def save_file(self, file_type: str, filename: str, content: bytes, metadata: dict) -> str:
        target_date = date.today()
        dir_path = self._get_dir(file_type, target_date)
        file_path = dir_path / filename
        file_path.write_bytes(content)

        meta = {
            "source": metadata.get("source", ""),
            "url": metadata.get("url", ""),
            "title": metadata.get("title", ""),
            "collected_at": datetime.now().isoformat(),
            **metadata,
        }
        meta_path = self._meta_path(file_path)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        return str(file_path.relative_to(self.base_dir))

    def get_file(self, file_path: str) -> bytes:
        full_path = self.base_dir / file_path
        return full_path.read_bytes()

    def list_files(self, file_type: str, target_date: date = None) -> list[dict]:
        if target_date:
            dir_path = self._get_dir(file_type, target_date)
            dirs = [dir_path]
        else:
            type_dir = self.base_dir / file_type
            if not type_dir.exists():
                return []
            dirs = [p for p in type_dir.rglob("*") if p.is_dir() and not any(p.iterdir())]
            dirs = [type_dir]  # search recursively from type root

        results = []
        search_root = self.base_dir / file_type
        if not search_root.exists():
            return []

        for file_path in search_root.rglob("*"):
            if file_path.is_file() and not file_path.name.endswith(".meta.json"):
                if target_date:
                    expected_dir = self._get_dir(file_type, target_date)
                    if file_path.parent != expected_dir:
                        continue
                rel_path = str(file_path.relative_to(self.base_dir))
                meta = self.get_metadata(rel_path)
                results.append({"path": rel_path, "filename": file_path.name, **meta})

        return results

    def get_metadata(self, file_path: str) -> dict:
        full_path = self.base_dir / file_path
        meta_path = self._meta_path(full_path)
        if meta_path.exists():
            return json.loads(meta_path.read_text(encoding="utf-8"))
        return {}
