"""Regenerate hashes after final edits. Never itself certifies the package."""
import hashlib
import json
from pathlib import Path
from validate_kit import files_in

root = Path(__file__).resolve().parents[1]
manifest = {'schema_version': 1, 'version': '2.0.0', 'files': {
    p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in files_in(root) if p.name != 'MANIFEST.json'}}
(root / 'MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
