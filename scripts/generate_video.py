"""Create an original 12-second color-card video with three synthetic tones."""
import math
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import wave

ROOT=Path(__file__).resolve().parents[1]
FONT={
'A':['01110','10001','10001','11111','10001','10001','10001'],
'B':['11110','10001','10001','11110','10001','10001','11110'],
'E':['11111','10000','10000','11110','10000','10000','11111'],
'H':['10001','10001','10001','11111','10001','10001','10001'],
'I':['11111','00100','00100','00100','00100','00100','11111'],
'L':['10000','10000','10000','10000','10000','10000','11111'],
'O':['01110','10001','10001','10001','10001','10001','01110'],
'P':['11110','10001','10001','11110','10000','10000','10000'],
'R':['11110','10001','10001','11110','10100','10010','10001'],
'T':['11111','00100','00100','00100','00100','00100','00100'],
'1':['00100','01100','00100','00100','00100','00100','01110'],
'2':['01110','10001','00001','00010','00100','01000','11111'],
'3':['11110','00001','00001','01110','00001','00001','11110'],
'5':['11111','10000','10000','11110','00001','00001','11110'],
'7':['11111','00001','00010','00100','01000','01000','01000'],
'9':['01110','10001','10001','01111','00001','00001','01110'],
'-':['00000','00000','00000','11111','00000','00000','00000'],
' ':['00000']*7,
}


def generate():
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:raise SystemExit('Install ffmpeg first: brew install ffmpeg')
    target=ROOT/'test-fixtures/video-evidence.mp4';target.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='gemini-fixture-') as tmp:
        tmp=Path(tmp)
        for n,color in enumerate([(190,20,25),(25,55,185),(20,135,50)]):
            pixels=bytearray(bytes(color)*(320*180))
            for text,y0 in [('ALPHA 17',25),('BETA 25',65)]+([('ORBIT-7391',115)] if n==2 else []):
                for j,char in enumerate(text):
                    for y,row in enumerate(FONT[char]):
                        for x,value in enumerate(row):
                            if value=='1':
                                for dy in range(3):
                                    for dx in range(3):
                                        pos=((y0+y*3+dy)*320+25+j*18+x*3+dx)*3
                                        pixels[pos:pos+3]=b'\xff\xff\xff'
            (tmp/f'frame{n}.ppm').write_bytes(b'P6\n320 180\n255\n'+pixels)
        with wave.open(str(tmp/'tones.wav'),'wb') as audio:
            audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000)
            samples=[]
            for i in range(12*16000):
                t=i/16000;on=any(a<=t<a+.4 for a in (.5,1.5,2.5))
                samples.append(struct.pack('<h',int(10000*math.sin(2*math.pi*440*t)) if on else 0))
            audio.writeframes(b''.join(samples))
        subprocess.run([ffmpeg,'-v','error','-y','-framerate','1/4','-i',str(tmp/'frame%d.ppm'),'-i',str(tmp/'tones.wav'),'-t','12','-vf','fps=12','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-map_metadata','-1','-movflags','+faststart',str(target)],check=True)
    return target


if __name__=='__main__':print(generate())
