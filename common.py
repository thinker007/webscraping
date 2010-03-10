#
# Common web scraping related functions
#
#

import os
import gzip
import re
import time
import urllib
import urllib2
from urlparse import urlparse
import string
from StringIO import StringIO
import htmlentitydefs
import socket
import tempfile
from threading import Thread
import Queue


def threaded_download(urls, proxies=[None]):
    """Download these urls in parallel using the given list of proxies 
    To use the same proxy multiple times in parallel provide it multiple times
    None means use no proxy

    Returns list of htmls in same order as urls
    """
    class Downloader(Thread):
        def __init__(self, urls):
            Thread.__init__(self)
            self.urls, self.results = urls, {}

        def run(self):
            try:
                while 1:
                    url = self.urls.get(block=False)
                    self.results[url] = download(url)
            except Queue.Empty:
                pass # finished

    # put urls into thread safe queue
    queue = Queue.Queue()
    for url in urls:
        queue.put(url)

    downloaders = []
    for proxy in proxies:
        downloader = Downloader(queue)
        downloaders.append(downloader)
        downloader.start()

    results = {}
    for downloader in downloaders:
        downloader.join()
        results = dict(results, **downloader.results)
    return [results[url] for url in urls]



def download(url, delay=3, output_dir='.', use_cache=True, retry=False, proxy=None):
    """Download this URL and return the HTML. Files are cached so only have to download once.

    url is what to download
    delay is the amount of time to delay after downloading
    output_dir is where to store cached files
    use_cache determines whether to load from cache if exists
    retry sets whether to try downloading webpage again if failed
    """
    socket.setdefaulttimeout(20)
    scheme, netloc, path, params, query, fragment = urlparse(url)
    if path.endswith('/'):
        path += 'index.html'
    output_file = netloc + path + ('?' + query if query else '')
    if use_cache and os.path.exists(output_file):
        html = open(output_file).read()
        if html or not retry:
            return html
        else:
            print 'Redownloading'
    # need to download file
    print url
    if not os.path.exists(os.path.dirname(output_file)):
        os.makedirs(os.path.dirname(output_file))
    # crawl slowly to reduce risk of being blocked
    time.sleep(delay) 
    # set the user agent and compression for url requests
    headers = {'User-agent': 'Mozilla/5.0', 'Accept-encoding': 'gzip'}
    opener = urllib2.build_opener()
    if proxy:
        opener.add_handler(urllib2.ProxyHandler({'http' : proxy}))
    try:
        response = opener.open(urllib2.Request(url, None, headers))
    except urllib2.URLError, e:
        # create empty file, so don't repeat downloading again
        print e
        html = ''
        open(output_file, 'w').write(html)
    else:
        # download completed successfully
        try:
            html = response.read()
        except socket.timeout:
            html = ''
        else:
            if response.headers.get('content-encoding') == 'gzip':
                # data came back gzip-compressed so decompress it          
                html = gzip.GzipFile(fileobj=StringIO(html)).read()
            _, tmp_file = tempfile.mkstemp()
            open(tmp_file, 'w').write(html)
            os.rename(tmp_file, output_file) # atomic write
    return to_ascii(html)


def to_ascii(html):
    #html = html.decode('utf-8')
    return ''.join(c for c in html if ord(c) < 128)


def unique(l):
    """Remove duplicates from list, while maintaining order
    """
    checked = []
    for e in l:
        if e not in checked:
            checked.append(e)
    return checked


def remove_tags(html, keep_children=True):
    """Remove HTML tags leaving just text
    If keep children is True then keep text within child tags
    """
    if not keep_children:
        html = re.compile('<.*?>.*?</.*?>', re.DOTALL).sub('', html)
    return re.compile('<[^<]*?>').sub('', html)


def select_options(html, attributes=''):
    """Extract options from HTML select box with given attributes
    >>> html = "Go: <select id='abc'><option value='1'>a</option><option value='2'>b</option></select>"
    >>> select_options(html, "id='abc'")
    [('1', 'a'), ('2', 'b')]
    """
    select_re = re.compile('<select[^>]*?%s[^>]*?>.*?</select>' % attributes, re.DOTALL)
    option_re = re.compile('<option[^>]*?value=[\'"](.*?)[\'"][^>]*?>(.*?)</option>', re.DOTALL)
    try:
        select_html = select_re.findall(html)[0]
    except IndexError:
        return []
    else:
        return option_re.findall(select_html)
    

def unescape(text):
    def fixup(m):
        text = m.group(0)
        if text[:2] == "&#":
            # character reference
            try:
                if text[:3] == "&#x":
                    return unichr(int(text[3:-1], 16))
                else:
                    return unichr(int(text[2:-1]))
            except ValueError:
                pass
        else:
            # named entity
            try:
                text = unichr(htmlentitydefs.name2codepoint[text[1:-1]])
            except KeyError:
                pass
        return text # leave as is
    return re.sub("&#?\w+;", fixup, urllib.unquote(text))
