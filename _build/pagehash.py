"""What counts as a change to a page, for sitemap lastmod purposes.

Shared by generate-pages.py and seed-page-dates.py so the two cannot drift; a
manifest written under one definition and read under another silently re-dates
the whole site.

lastmod is a claim about the content an index holds, not about the bytes.
Restyling a page, restamping its asset URLs or moving a script tag changes the
file without changing anything a reader or a crawler would notice, and dating
those changes is what taught search engines to ignore this sitemap in the
first place. So the hash is taken over the indexable content only:

  - executable <script> blocks are dropped; ld+json is kept, being structured
    data that search engines do read
  - <link> and <meta http-equiv> tags are dropped
  - ?v= asset stamps and the "Site last updated" line are dropped
  - whitespace is collapsed, so reflowed markup is not a change

Anything a reader would see - words, figures, links, headings, tables - still
counts, which is the point.
"""

import re
import hashlib

_SCRIPT = re.compile(
    r'<script(?![^>]*type=["\']application/ld\+json["\'])[^>]*>.*?</script>\s*',
    re.S | re.I)
_LINK = re.compile(r'<link\b[^>]*>\s*', re.I)
_VERSION = re.compile(r'\?v=[0-9a-f]+')
_UPDATED = re.compile(r'Site last updated: \d{4}-\d{2}-\d{2}')
_SPACE = re.compile(r'\s+')


def indexable(html):
    """The part of a page whose change is worth reporting to a crawler."""
    html = _SCRIPT.sub(' ', html)
    html = _LINK.sub(' ', html)
    html = _VERSION.sub('', html)
    html = _UPDATED.sub('Site last updated:', html)
    return _SPACE.sub(' ', html).strip()


def content_hash(html):
    return hashlib.sha256(indexable(html).encode()).hexdigest()[:16]
