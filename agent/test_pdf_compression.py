"""Offline PDF regressions using synthetic data; no credentials or portal access."""
import random
import tempfile
import unittest
from pathlib import Path

import pymupdf as pdf
from pdf_package import compress_images


class CompressionTests(unittest.TestCase):
    def test_unused_earlier_page_resource_does_not_skip_later_image(self):
        with tempfile.TemporaryDirectory(prefix='verifyxcity-pdf-test-') as folder:
            root=Path(folder)
            pixels=random.Random(42).randbytes(1200*900*3)
            pix=pdf.Pixmap(pdf.csRGB,1200,900,pixels,False)
            with pdf.open() as doc:
                first=doc.new_page()
                first.insert_text((30,40),'Synthetic report text must survive')
                xref=first.insert_image(pdf.Rect(20,100,550,500),stream=pix.tobytes('jpeg',jpg_quality=90))
                # Keep the image in page 1 resources, but remove its placement.
                content=doc.get_new_xref()
                doc.update_object(content,'<<>>')
                doc.update_stream(content,b'BT /helv 12 Tf 30 800 Td (Synthetic report text must survive) Tj ET')
                first.set_contents(content)
                second=doc.new_page()
                second.insert_image(pdf.Rect(20,100,550,500),xref=xref)
                original=root/'original.pdf'
                doc.save(original)
            with pdf.open(original) as source:
                self.assertTrue(source[0].get_images())
                self.assertFalse(source[0].get_image_rects(xref))
                self.assertTrue(source[1].get_image_rects(xref))
            compressed=root/'compressed.pdf'
            compress_images(original,compressed,100,60)
            with pdf.open(compressed) as result:
                self.assertEqual(result.page_count,2)
                self.assertIn('Synthetic report text must survive',result[0].get_text())
                widths=[result.extract_image(info[0])['width'] for info in result[1].get_images()
                        if result[1].get_image_rects(info[0])]
                self.assertTrue(widths)
                self.assertLess(max(widths),1200)
                for page in result:
                    page.get_pixmap(matrix=pdf.Matrix(0.5,0.5))
            self.assertLess(compressed.stat().st_size,original.stat().st_size)


if __name__=='__main__':
    unittest.main()
