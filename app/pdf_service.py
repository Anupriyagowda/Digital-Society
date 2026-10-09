from io import BytesIO

from flask import current_app, render_template, request, send_file, url_for
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _value(value):
    return str(value) if value not in (None, '') else '-'


def build_pdf(title, sections, qr_bytes=None):
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph(_value(current_app.config.get('SOCIETY_NAME', 'Digital Society')), styles['Title']),
        Paragraph(title, styles['Heading2']),
        Spacer(1, 8),
    ]

    if qr_bytes:
        qr_image = Image(BytesIO(qr_bytes), width=48 * mm, height=48 * mm)
        story.append(qr_image)
        story.append(Spacer(1, 8))

    for section_title, rows in sections:
        if section_title:
            story.append(Paragraph(section_title, styles['Heading3']))
        table = Table([[_value(label), _value(value)] for label, value in rows], colWidths=[48 * mm, 120 * mm])
        table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#d7dee8')),
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f2f5f8')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('LEFTPADDING', (0, 0), (-1, -1), 7),
            ('RIGHTPADDING', (0, 0), (-1, -1), 7),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(table)
        story.append(Spacer(1, 12))

    document.build(story)
    output.seek(0)
    return output


def preview_or_download(pdf, filename, title):
    if request.args.get('preview') == '1':
        return render_template(
            'pdf_preview.html',
            title=title,
            pdf_url=request.path + '?inline=1',
            download_url=request.path + '?download=1',
            back_url=request.referrer or url_for('main.dashboard'),
        )
    return send_file(
        pdf,
        mimetype='application/pdf',
        as_attachment=request.args.get('inline') != '1',
        download_name=filename,
    )
