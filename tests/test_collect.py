import unittest
from scripts.collect import parse, iso

class CollectTests(unittest.TestCase):
    def test_rss(self):
        raw=b'<rss><channel><item><title>Mars</title><link>https://example.com/mars</link><description>Decouverte</description><pubDate>Sun, 25 Oct 2026 12:00:00 GMT</pubDate></item></channel></rss>'
        result=parse(raw,'NASA')
        self.assertEqual(result[0]['title'],'Mars')
        self.assertEqual(result[0]['source'],'NASA')
    def test_atom(self):
        raw=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Lune</title><link href="https://example.com/lune"/><updated>2026-10-25T12:00:00Z</updated></entry></feed>'
        self.assertEqual(parse(raw,'ESA')[0]['url'],'https://example.com/lune')
    def test_bad_date(self):
        self.assertEqual(iso('not a date'),'')
if __name__=='__main__':
    unittest.main()
