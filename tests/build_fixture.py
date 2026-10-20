"""Regenerate the synthetic English PDF; requires reportlab, not an AI API."""
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from xml.sax.saxutils import escape


def build(destination: Path) -> None:
    source = destination.with_name('clean-text.source.txt').read_text(encoding='utf-8')
    page_one = source.split('PAGE 1\n', 1)[1].split('\nPAGE 2\n', 1)[0]
    page_two = source.split('\nPAGE 2\n', 1)[1]
    styles = getSampleStyleSheet()
    styles['BodyText'].fontName = 'Helvetica'
    styles['BodyText'].fontSize = 11
    styles['BodyText'].leading = 16
    doc = SimpleDocTemplate(str(destination), pagesize=A4, rightMargin=45, leftMargin=45, topMargin=45, bottomMargin=45, title='Systems at Work - Synthetic Acceptance Fixture', author='Test Library')
    story = [Paragraph('Systems at Work', styles['Title']), Paragraph('Synthetic acceptance fixture | Author: Test Library', styles['BodyText']), Spacer(1, 18)]
    for block in page_one.strip().split('\n\n'):
        if block.startswith('Metric |'):
            table = Table([[cell.strip() for cell in row.split('|')] for row in block.splitlines()], colWidths=[245, 65, 65])
            table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 0.5, colors.grey), ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eeeeee')), ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'), ('FONTSIZE', (0, 0), (-1, -1), 10), ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8)]))
            story.append(table)
        else:
            story.append(Paragraph(escape(block).replace('\n', '<br/>'), styles['BodyText']))
        story.append(Spacer(1, 14))
    story.append(PageBreak())
    for block in page_two.strip().split('\n\n'):
        story.append(Paragraph(escape(block).replace('\n', '<br/>'), styles['BodyText']))
        story.append(Spacer(1, 14))

    def footer(canvas, document):
        canvas.setFont('Helvetica', 9)
        canvas.drawString(45, 27, 'TEST - synthetic source, no private information')
        canvas.drawRightString(A4[0] - 45, 27, f'Page {document.page}')

    doc.build(story, onFirstPage=footer, onLaterPages=footer)


if __name__ == '__main__':
    build(Path(__file__).parent / 'fixtures' / 'clean-text.pdf')
