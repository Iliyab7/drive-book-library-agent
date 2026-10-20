"""Offline portability checks; these do not certify a live library deployment."""
from pathlib import Path
import csv
import io
import json
import re
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from validate_kit import validate  # noqa: E402


class KitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / 'kit'
        shutil.copytree(ROOT, self.root, ignore=shutil.ignore_patterns('__pycache__', '.git'))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_actual_bundle_is_valid(self) -> None:
        self.assertEqual(validate(ROOT), [])

    def test_skill_references_survive_standalone_installation(self) -> None:
        installed = Path(self.temporary.name) / 'installed-skill'
        shutil.copytree(ROOT / '.agents' / 'skills' / 'drive-book-library', installed)
        for document in installed.rglob('*.md'):
            for link in re.findall(r'\[[^\]]*\]\(([^\s)]+)\)', document.read_text(encoding='utf-8')):
                if link.startswith(('https://', 'http://', '#')):
                    continue
                target = (document.parent / link.split('#', 1)[0]).resolve()
                self.assertTrue(target.is_relative_to(installed.resolve()))
                self.assertTrue(target.is_file())

    def test_missing_local_reference_is_rejected(self) -> None:
        path = self.root / 'docs' / 'WORKFLOW-FA.md'
        path.unlink()
        self.assertTrue(any('reference' in e for e in validate(self.root)))

    def test_parent_path_reference_is_rejected(self) -> None:
        with (self.root / 'README.md').open('a', encoding='utf-8') as handle:
            handle.write('\n[bad](../../outside.txt)\n')
        self.assertTrue(any('escapes' in e for e in validate(self.root)))

    def test_private_drive_target_is_rejected(self) -> None:
        path = self.root / 'templates' / 'library.config.example.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['root_folder_url'] = 'https://' + 'drive.google.com/drive/folders/' + 'SyntheticPrivateId1234567'
        path.write_text(json.dumps(data), encoding='utf-8')
        self.assertTrue(any('private target' in e for e in validate(self.root)))

    def test_secret_is_rejected(self) -> None:
        (self.root / 'accidental.txt').write_text('github' + '_pat_' + 'a' * 24, encoding='utf-8')
        self.assertTrue(any('credential' in e for e in validate(self.root)))

    def test_host_path_is_rejected(self) -> None:
        (self.root / 'accidental.txt').write_text('C:' + '/Users/' + 'example/private', encoding='utf-8')
        self.assertTrue(any('host path' in e for e in validate(self.root)))

    def test_malformed_json_is_rejected(self) -> None:
        (self.root / 'templates' / 'agent-report.example.json').write_text('{', encoding='utf-8')
        self.assertTrue(any('JSON' in e for e in validate(self.root)))

    def test_ready_template_is_rejected(self) -> None:
        path = self.root / 'templates' / 'library.config.example.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['readiness']['ready_for_pdf'] = True
        path.write_text(json.dumps(data), encoding='utf-8')
        self.assertTrue(any('readiness template' in e for e in validate(self.root)))

    def test_duplicate_acceptance_id_is_rejected(self) -> None:
        path = self.root / 'acceptance' / 'ACCEPTANCE-FA.csv'
        rows = list(csv.reader(io.StringIO(path.read_text(encoding='utf-8-sig'))))
        rows.append(rows[1])
        with path.open('w', encoding='utf-8-sig', newline='') as handle:
            csv.writer(handle).writerows(rows)
        self.assertTrue(any('acceptance identities' in e for e in validate(self.root)))

    def test_schema_identity_must_be_a_field(self) -> None:
        path = self.root / 'templates' / 'sheets.schema.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['tabs'][0]['row_identity'] = 'absent'
        path.write_text(json.dumps(data), encoding='utf-8')
        self.assertTrue(any('sheet identity' in e for e in validate(self.root)))

    def test_manifest_detects_changed_file(self) -> None:
        with (self.root / 'README.md').open('a', encoding='utf-8') as handle:
            handle.write('\nA changed artifact.\n')
        self.assertTrue(any('manifest hash' in e for e in validate(self.root)))


if __name__ == '__main__':
    unittest.main()
