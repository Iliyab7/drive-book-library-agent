"""Read back the synthetic PDF's actual text and page structure."""
from pathlib import Path
import json
import unittest
from pypdf import PdfReader


class FixtureTests(unittest.TestCase):
    def test_pdf_preserves_the_published_test_facts(self) -> None:
        fixtures = Path(__file__).parent / 'fixtures'
        expected = json.loads((fixtures / 'expected-facts.json').read_text(encoding='utf-8'))
        reader = PdfReader(fixtures / expected['pdf'])
        self.assertEqual(len(reader.pages), expected['pages'])
        text = '\n'.join(page.extract_text() for page in reader.pages)
        for fact in expected['facts']:
            self.assertIn(fact['source_phrase'], text)
        for index, page in enumerate(reader.pages, 1):
            self.assertIn(f'Page {index}', page.extract_text())
        self.assertIn('END OF SYNTHETIC FIXTURE', reader.pages[-1].extract_text())


if __name__ == '__main__':
    unittest.main()
