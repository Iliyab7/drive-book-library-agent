"""Full method text survives installation and loads without repository access."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from instruction_memory import SOURCES, prepare_instructions, load_active_instructions, manifest_hash, digest


class InstructionMemoryTests(unittest.TestCase):
    def setUp(self):
        # Installation explicitly reads the package once.
        self.config = {'template_only': False, 'inbox_url': 'synthetic-inbox', 'output_url': 'synthetic-output',
                       'locations': {k: {'reference': f'synthetic-{k}'} for k in ('files','catalog','shared_memory','checkpoints')},
                       'runtime': {'coordinator': 'test'}, 'coordination': {'serialization_verified': False},
                       'schedule': {'id': None, 'limitation': 'synthetic manual test'}}
        self.packet = prepare_instructions('synthetic-source-revision', 'test-method-1', self.config, chunk_chars=300)
        self.expected = {key: (ROOT / path).read_text(encoding='utf-8') for key, path in SOURCES.items()}

    def active(self):
        pointer = deepcopy(self.packet['pointer']); pointer['activation_status'] = 'active'
        return pointer

    def test_full_runbook_loaded_from_paginated_memory_without_repository(self):
        # These are simulated persisted rows read in pages, including an empty page.
        serialized = json.dumps(self.packet, ensure_ascii=False)
        stored = json.loads(serialized)
        pages = [stored['rows'][:4], [], stored['rows'][4:]]
        rows = [row for page in pages for row in page]
        pointer = self.active()
        # A fresh turn cannot read ANY local package file. All seven full texts
        # are reconstructed exactly from memory, including requirements/roles.
        with patch.object(Path, 'read_text', side_effect=AssertionError('repository unavailable')):
            texts = load_active_instructions(pointer, stored['manifest'], list(reversed(rows)), deepcopy(pointer), stored['config'])
        self.assertEqual(texts, self.expected)
        self.assertIn('original.pdf', texts['skill'])
        self.assertIn('Review', texts['coordinator'])
        self.assertIn('checkpoint', texts['workflow'])
        self.assertIn('active_config', texts['coordinator'])

    def test_staged_partial_corrupt_duplicate_memory_rejected(self):
        with self.assertRaisesRegex(ValueError, 'not active'):
            load_active_instructions(self.packet['pointer'], self.packet['manifest'], self.packet['rows'], self.packet['pointer'], self.packet['config'])
        for mode in ('missing', 'corrupt', 'duplicate'):
            rows = deepcopy(self.packet['rows'])
            if mode == 'missing': rows.pop()
            if mode == 'corrupt': rows[0]['instruction_text'] += ' changed'
            if mode == 'duplicate': rows.append(deepcopy(rows[0]))
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                load_active_instructions(self.active(), self.packet['manifest'], rows, self.active(), self.packet['config'])
        broken = deepcopy(self.packet['manifest'])
        broken['components'][0].update(chunks=0, sha256=digest(''))
        pointer = self.active(); pointer['bundle_sha256'] = manifest_hash(broken)
        with self.assertRaisesRegex(ValueError, 'positive chunks'):
            load_active_instructions(pointer, broken, self.packet['rows'], pointer, self.packet['config'])

    def test_explicit_upgrade_retains_previous_memory_and_no_mixed_activation(self):
        old = deepcopy(self.packet)
        next_config = deepcopy(self.config); next_config['output_url'] = 'synthetic-new-output'
        newer = prepare_instructions('synthetic-next-source', 'test-method-2', next_config, chunk_chars=300)
        active_new = dict(newer['pointer'], activation_status='active')
        history = old['rows'] + newer['rows']
        self.assertEqual(load_active_instructions(self.active(), old['manifest'], history, self.active(), old['config']), self.expected)
        self.assertEqual(load_active_instructions(active_new, newer['manifest'], history, active_new, newer['config']), self.expected)
        with self.assertRaisesRegex(ValueError, 'changed during read'):
            load_active_instructions(self.active(), old['manifest'], history, active_new, old['config'])
        with self.assertRaisesRegex(ValueError, 'manifest mismatch'):
            load_active_instructions(active_new, old['manifest'], history, active_new, old['config'])
        with self.assertRaisesRegex(ValueError, 'config'):
            load_active_instructions(self.active(), old['manifest'], history, self.active(), newer['config'])
        # Rollback of the pointer also selects the exact old config, still intact.
        self.assertEqual(old['config']['record_content_json']['output_url'], 'synthetic-output')
        self.assertEqual(self.packet, old)

    def test_missing_changed_or_empty_operational_config_blocks_startup(self):
        changed = deepcopy(self.packet['config']); changed['record_content_json']['output_url'] = 'changed'
        for config in ({}, changed):
            with self.subTest(config=config), self.assertRaisesRegex(ValueError, 'config'):
                load_active_instructions(self.active(), self.packet['manifest'], self.packet['rows'], self.active(), config)
        with self.assertRaisesRegex(ValueError, 'config'):
            prepare_instructions('source', 'revision', {})


if __name__ == '__main__':
    unittest.main()
