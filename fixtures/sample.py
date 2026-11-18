"""Generate an original, one-page English test paper. The fixture text is CC0."""
from pathlib import Path
import sys
import pymupdf

def make(path):
    doc=pymupdf.open()
    page=doc.new_page()
    page.insert_text((72,100),"A small temperature study",fontsize=17)
    page.insert_text((72,160),"We tested 12 samples at 23.5 degrees Celsius [1].",fontsize=12)
    page.insert_text((72,190),"The measured value was x = 2. The results were reproducible.",fontsize=12)
    doc.save(path)
    doc.close()

if __name__=="__main__":
    make(Path(sys.argv[1]))
