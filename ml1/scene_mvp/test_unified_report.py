from html.parser import HTMLParser
import unittest
from build_unified_review import render
from scene_mvp.unified_review import assemble


class Links(HTMLParser):
    def __init__(self):super().__init__();self.ids=set();self.hrefs=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if 'id' in a:self.ids.add(a['id'])
        if tag=='a':self.hrefs.append(a['href'])


class UnifiedReportTests(unittest.TestCase):
    def test_pending_cases_do_not_link_to_missing_sections(self):
        catalog={'source_pdf_sha256':'c'*64,'records':[
            {'filename':'<X-1>.mov','video_sha256':'a'*64,'video_id':'X-1','reference_timestamp_sec':2,'annotation_type':'one'},
            {'filename':'X-2.mov','video_sha256':'b'*64,'video_id':'X-2','reference_timestamp_sec':3,'annotation_type':'two'}]}
        data=assemble(catalog,[{'source_video_sha256':'a'*64,'kind':'human_cash_transfer','events':[]}])
        page=render(data);links=Links();links.feed(page)
        self.assertEqual(len(links.hrefs),1)
        self.assertTrue(all(h.startswith('#') and h[1:] in links.ids for h in links.hrefs))
        self.assertIn('&lt;X-1&gt;.mov',page)
        self.assertIn('Пока нет анализа',page)


if __name__=='__main__':unittest.main()
