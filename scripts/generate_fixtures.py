"""Generate original synthetic PNG, PDF and DOCX test material (MIT)."""
import struct,zipfile,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def fixtures():
    directory = ROOT / 'test-fixtures'
    directory.mkdir(exist_ok=True)
    # White canvas, red rectangle on left, blue circle on right.
    rows = []
    for y in range(160):
        row = bytearray()
        for x in range(320):
            color = (235, 30, 30) if 30 <= x < 130 and 30 <= y < 130 else ((25, 50, 235) if (x-240)**2+(y-80)**2 < 50**2 else (255,255,255))
            row.extend(color)
        rows.append(b'\0'+bytes(row))
    def chunk(name, data):
        return struct.pack('!I',len(data))+name+data+struct.pack('!I',zlib.crc32(name+data)&0xffffffff)
    png = b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',320,160,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b'')
    (directory/'shapes.png').write_bytes(png)
    stream = b'BT /F1 24 Tf 50 740 Td (Verification code: ORBIT-7391) Tj 0 -40 Td (Alpha: 17   Beta: 25) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    pdf=b'%PDF-1.4\n'; offsets=[0]
    for i,o in enumerate(objects,1):
        offsets.append(len(pdf));pdf+=str(i).encode()+b' 0 obj\n'+o+b'\nendobj\n'
    start=len(pdf);pdf+=b'xref\n0 6\n0000000000 65535 f \n'+b''.join(f'{x:010d} 00000 n \n'.encode() for x in offsets[1:])+b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n'+str(start).encode()+b'\n%%EOF'
    (directory/'verification.pdf').write_bytes(pdf)
    with zipfile.ZipFile(directory/'verification.docx','w') as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Verification code: CEDAR-4826. Project Maple has 37 tasks.</w:t></w:r></w:p><w:sectPr/></w:body></w:document>')
    return directory


if __name__=='__main__':
    print(fixtures())
