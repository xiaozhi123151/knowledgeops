import io

from reportlab.pdfgen import canvas


def sample_pdf():
    out = io.BytesIO()
    pdf = canvas.Canvas(out, invariant=1)
    pdf.drawString(40, 720, 'Redis AOF persistence logs every write operation.')
    pdf.drawString(40, 700, 'Redis RDB creates periodic snapshots.')
    pdf.showPage()
    pdf.drawString(40, 720, 'Qdrant provides vector similarity search.')
    pdf.save()
    return out.getvalue()
