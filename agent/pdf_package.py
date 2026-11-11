"""Local-only report/photo packaging. Keep report text and every attachment."""
from pathlib import Path
import pymupdf as pdf


def assemble_report(native_report, attachments, output, full_page_indexes=()):
    """Numbered four-photo annex; explicitly identified document scans stay full-page."""
    full_page_indexes=set(full_page_indexes)
    with pdf.open(native_report) as doc:
        tile_page=None
        tile_index=0
        for index,path in enumerate(attachments,1):
            content=Path(path).read_bytes()
            with pdf.open(stream=content) as source:
                if source.is_pdf:
                    tile_page=None
                    tile_index=0
                    doc.insert_pdf(source)
                    continue
            if index in full_page_indexes:
                tile_page=None
                tile_index=0
                added=doc.new_page(width=595,height=842)
                added.insert_text((15,17),f'Attachment {index} of {len(attachments)}',fontsize=10)
                added.insert_image(pdf.Rect(10,25,585,832),stream=content,keep_proportion=True)
            else:
                if tile_page is None or tile_index==4:
                    tile_page=doc.new_page(width=595,height=842)
                    tile_index=0
                col,row=tile_index%2,tile_index//2
                x,y=10+col*292,10+row*416
                tile_page.insert_text((x+3,y+13),f'Attachment {index} of {len(attachments)}',fontsize=9)
                tile_page.insert_image(pdf.Rect(x+2,y+22,x+280,y+403),stream=content,keep_proportion=True)
                tile_index+=1
        doc.ez_save(output)


def compress_images(raw, output, dpi, quality):
    """Recompress attachment images using their actual placed size; native report untouched.
    Full-page attachment scans retain at least 160 DPI and quality 80.
    """
    with pdf.open(raw) as doc:
        seen=set()
        for page in list(doc):
            for info in page.get_images(full=True):
                xref=info[0]
                if xref in seen:
                    continue
                rects=page.get_image_rects(xref)
                if not rects:
                    # Generated PDFs can list an image in an earlier page's
                    # resources without drawing it there. Do not mark it seen
                    # until its actual placement is found on a later page.
                    continue
                seen.add(xref)
                full_page=max(r.get_area() for r in rects) > page.rect.get_area()*0.55
                target_dpi=max(dpi,200) if page.number == 0 else (max(dpi,160) if full_page else dpi)
                target_quality=max(quality,85) if page.number == 0 else (max(quality,80) if full_page else quality)
                pix=pdf.Pixmap(doc,xref)
                if pix.colorspace is None:
                    continue
                if pix.colorspace.n>3:
                    pix=pdf.Pixmap(pdf.csRGB,pix)
                if info[1]:
                    pix=pdf.Pixmap(pix,pdf.Pixmap(doc,info[1]))
                width=max(r.width for r in rects)*target_dpi/72
                height=max(r.height for r in rects)*target_dpi/72
                scale=min(1,width/pix.width,height/pix.height)
                if scale<1:
                    pix=pdf.Pixmap(pix,max(1,round(pix.width*scale)),max(1,round(pix.height*scale)),None)
                if pix.alpha:
                    page.replace_image(xref,pixmap=pix)
                else:
                    page.replace_image(xref,stream=pix.tobytes('jpeg',jpg_quality=target_quality))
        doc.save(output,garbage=4,clean=True,deflate=True,use_objstms=1)
