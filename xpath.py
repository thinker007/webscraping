#
# Description:
# This module implements a subset of the XPath standard:
#  - tags
#  - indices
#  - attributes
#  - descendants
# Plus a few extensions useful to my work:
#  - attributes can contain regular expressions
#  - indices can be negative
#
# Generally XPath solutions will normalize the HTML into XHTML before selecting nodes.
# However this module tries to navigate the HTML structure directly without normalizing.
# In some cases I have found this faster/more accurate than using lxml.html and in other cases less so.
#
# Author: Richard Penman (richard@sitescraper.net)
# License: LGPL
#
#
# TODO:
#  - convert to class to more efficiently handle html
#  -  and buffer tree selections
#  - parent
#  - search by text: text() == '...'
#  - return xpath for most similar to text
#  - change to breadth first search for faster finish with single element

import re
import urllib2
from urlparse import urljoin, urlsplit
from optparse import OptionParser
from webscraping import common

DEBUG = False
# tags that do not contain content and so can be safely skipped
EMPTY_TAGS = 'br', 'hr'



class XPathException(Exception):
    pass


def search(html, xpath, remove=None):
    """Query HTML document using XPath
    
    remove is a list of tags to ignore

    >>> search('<span>1</span><div>abc<a>LINK 1</a><div><a>LINK 2</a>def</div>abc</div>ghi<div><a>LINK 3</a>jkl</div>', '/div/a')
    ['LINK 1', 'LINK 3']
    >>> search('<div>abc<a class="link">LINK 1</a><div><a>LINK 2</a>def</div>abc</div>ghi<div><a class="link">LINK 3</a>jkl</div>', '/div[1]/a[@class="link"]')
    ['LINK 1']
    >>> search('<div>abc<a class="link">LINK 1</a><div><a>LINK 2</a>def</div>abc</div>ghi<div><a class="link">LINK 3</a>jkl</div>', '/div[1]//a')
    ['LINK 1', 'LINK 2']
    >>> search('<div>abc<a class="link">LINK 1</a></div>', '/div/a/@class')
    ['link']
    
    # test scraping a large amount of content
    >>> len(search('<div><span>!</span></div>' * 10000, '//span'))
    10000
    """
    orig_html = html
    html = clean_html(html, remove)
    contexts = [html] # initial context is entire webpage
    parent_attributes = []
    for tag_i, (separator, tag, index, attributes) in enumerate(xpath_iter(xpath)):
        children = []
        if tag == '..':
            # parent
            raise XPathException('.. not yet supported')
        elif tag == 'text()':
            # extract child text
            for context in contexts:
                children.append(common.remove_tags(context, keep_children=False))
        elif tag.startswith('@'):
            # selecting attribute
            name = tag[1:].lower()
            for a in parent_attributes:
                children.append(a.get(name, ''))
        else:
            # have tag
            parent_attributes = []
            for context in contexts:
                # search direct children if / and all descendants if //
                search = separator == '' and find_children or find_descendants
                # XXX change to iterator
                matches = search(context, tag)
                for child_i, child in enumerate(matches):
                    if index is None or index == child_i + 1 or index == -1 and len(matches) == child_i + 1:
                        # matches index if defined
                        child_attributes = get_attributes(child)
                        if match_attributes(attributes, child_attributes):
                            # child matches tag and any defined indices or attributes
                            children.append(get_content(child))
                            parent_attributes.append(child_attributes)
        if not children and tag == 'tbody':
            pass # skip tbody, which firefox includes in xpath when does not exist
        else:
            contexts = children
        if not contexts:
            if DEBUG:
                attributes_s = attributes and ''.join('[@%s="%s"]' % a for a in attributes) or ''
                print 'No matches for <%s%s%s> (tag %d)' % (tag, index and '[%d]' % index or '', attributes_s, tag_i + 1)
            break
    return contexts


def get(*args, **kwargs):
    """Return first element from search
    """
    return common.first(search(*args, **kwargs))


def clean_html(html, tags):
    """Remove specified unhelpful tags and comments
    """
    html = re.compile('<!--.*?-->', re.DOTALL).sub('', html) # remove comments
    if tags:
        for tag in tags:
            html = re.compile('<' + tag + '[^>]*?/>', re.DOTALL | re.IGNORECASE).sub('', html)
            html = re.compile('<' + tag + '[^>]*?>.*?</' + tag + '>', re.DOTALL | re.IGNORECASE).sub('', html)
            html = re.compile('<' + tag + '[^>]*?>', re.DOTALL | re.IGNORECASE).sub('', html)
    return html


def xpath_iter(xpath):
    """Return an iterator of the xpath parsed into the separator, tag, index, and attributes

    >>> list(xpath_iter('/div[1]//span[@class="text"]'))
    [('', 'div', 1, []), ('/', 'span', None, [('class', 'text')])]
    >>> list(xpath_iter('/div[@id="content"]//span[1][@class="text"][@title=""]/a'))
    [('', 'div', None, [('id', 'content')]), ('/', 'span', 1, [('class', 'text'), ('title', '')]), ('', 'a', None, [])]
    """
    for separator, token in re.compile('(|/|\.\.)/([^/]+)').findall(xpath):
        index, attributes = None, []
        if '[' in token:
            tag = token[:token.find('[')]
            for attribute in re.compile('\[(.*?)\]').findall(token):
                try:
                    index = int(attribute)
                except ValueError:
                    match = re.compile('@(.*?)=["\']?(.*?)["\']?$').search(attribute)
                    if match:
                        key, value = match.groups()
                        attributes.append((key.lower(), value.lower()))
                    else:
                        raise XPathException('Unknown format: ' + attribute)
        else:
            tag = token
        yield separator, tag, index, attributes



attributes_regex = re.compile('([\w-]+)=(".*?"|\'.*?\'|\w+)', re.DOTALL)
def get_attributes(html):
    """Extract the attributes of the passed HTML tag

    >>> get_attributes('<div id="ID" name="MY NAME" max-width="20" class=abc>content <span class="inner name">SPAN</span></div>')
    {'max-width': '20', 'class': 'abc', 'id': 'ID', 'name': 'MY NAME'}
    """
    if '>' in html:
        html = html[:html.index('>')]
    return dict((name.lower().strip(), value.strip('\'" ')) for (name, value) in attributes_regex.findall(html))


def match_attributes(desired_attributes, available_attributes):
    """Returns True if all of desired attributes are in available attributes
    Supports regex, which is not part of the XPath standard but is so useful!

    >>> match_attributes([], {})
    True
    >>> match_attributes([('class', 'test')], {})
    False
    >>> match_attributes([], {'id':'test', 'class':'test2'})
    True
    >>> match_attributes([('class', 'test')], {'id':'test', 'class':'test2'})
    False
    >>> match_attributes([('class', 'test')], {'id':'test2', 'class':'test'})
    True
    >>> match_attributes([('class', 'test'), ('id', 'content')], {'id':'test', 'class':'content'})
    False
    >>> match_attributes([('class', 'test'), ('id', 'content')], {'id':'content', 'class':'test'})
    True
    >>> match_attributes([('class', 'test\d')], {'id':'test', 'class':'test2'})
    True
    >>> match_attributes([('class', 'test\d')], {'id':'test2', 'class':'test'})
    False
    """
    for name, value in desired_attributes:
        if name not in available_attributes or not re.match(re.compile(value + '$', re.IGNORECASE), available_attributes[name]):
            return False
    return True


content_regex = re.compile('<.*?>(.*)</.*?>$', re.DOTALL)
def get_content(html, default=''):
    """Extract the child HTML of a the passed HTML tag

    >>> get_content('<div id="ID" name="NAME">content <span>SPAN</span></div>')
    'content <span>SPAN</span>'
    """
    match = content_regex.match(html)
    if match:
        content = match.groups()[0]
    else:
        content = default
    return content



def find_children(html, tag):
    """Find children with this tag type

    >>> find_children('<span>1</span><div>abc<div>def</div>abc</div>ghi<div>jkl</div>', 'div')
    ['<div>abc<div>def</div>abc</div>', '<div>jkl</div>']
    """
    results = []
    found = True
    while found:
        html = jump_next_tag(html)
        if html:
            tag_html, html = split_tag(html)
            if tag_html:
                #print 'tag:', get_tag(tag_html)
                if tag.lower() in ('*', get_tag(tag_html).lower()):
                    results.append(tag_html)
            else:
                found = False
        else:
            found = False
    return results


def find_descendants(html, tag):
    """Find descendants with this tag type

    >>> find_descendants('<span>1</span><div>abc<div>def</div>abc</div>ghi<div>jkl</div>', 'div')
    ['<div>abc<div>def</div>abc</div>', '<div>def</div>', '<div>jkl</div>']
    """
    if tag == '*':
        raise XPathException("`*' not currently supported for // because too inefficient")
    results = []
    for match in re.compile('<%s' % tag, re.DOTALL | re.IGNORECASE).finditer(html):
        tag_html, _ = split_tag(html[match.start():])
        results.append(tag_html)
    return results


tag_regex = re.compile('<(\w+)')
def jump_next_tag(html):
    """Return html at start of next tag

    >>> jump_next_tag('<div>abc</div>')
    '<div>abc</div>'
    >>> jump_next_tag(' <div>abc</div>')
    '<div>abc</div>'
    >>> jump_next_tag('</span> <div>abc</div>')
    '<div>abc</div>'
    >>> jump_next_tag('<br> <div>abc</div>')
    '<div>abc</div>'
    """
    while 1:
        match = tag_regex.search(html)
        if match:
            # XXX check match
            if match.groups()[0].lower() in EMPTY_TAGS:
                html = html[match.end():]
            else:
                return html[match.start():]
        else:
            return None


def get_tag(html):
    """Find tag type at this location

    >>> get_tag('<div>abc</div>')
    'div'
    >>> get_tag(' <div>')
    >>> get_tag('div')
    """
    match = tag_regex.match(html)
    if match:
        return match.groups()[0]
    else:
        return None


def split_tag(html):
    """Extract starting tag from HTML

    >>> split_tag('<div>abc<div>def</div>abc</div>ghi<div>jkl</div>')
    ('<div>abc<div>def</div>abc</div>', 'ghi<div>jkl</div>')
    >>> split_tag('<br /><div>abc</div>')
    ('<br />', '<div>abc</div>')
    >>> split_tag('<div>abc<div>def</div>abc</span>')
    ('<div>abc<div>def</div>abc</span></div>', '')
    """
    tag = get_tag(html)
    depth = 0 # how far nested
    for match in re.compile('</?%s.*?>' % tag, re.DOTALL | re.IGNORECASE).finditer(html):
        if html[match.start() + 1] == '/':
            depth -= 1
        elif html[match.end() - 2] == '/':
            pass # tag starts and ends (eg <br />)
        else:
            depth += 1
        if depth == 0:
            # found top level match
            i = match.end()
            return html[:i], html[i:]
    return html + '</%s>' % tag, ''


def get_links(html, url=None, local=True, external=True):
    """Return all links from html and convert relative to absolute if source url is provided

    local determines whether to include links from same domain
    external determines whether to include linkes from other domains
    """
    def normalize_link(link):
        if urlsplit(link).scheme in ('http', 'https', ''):
            if '#' in link:
                link = link[:link.index('#')]
            if url:
                link = urljoin(url, link)
                if not local and common.same_domain(url, link):
                    # local links not included
                    link = None
                if not external and not common.same_domain(url, link):
                    # external links not included
                    link = None
        else:
            link = None # ignore mailto, etc
        return link
    a_links = search(html, '//a/@href')
    js_links = re.findall('location.href ?= ?[\'"](.*?)[\'"]', html)
    links = []
    for link in a_links + js_links:
        try:
            link = normalize_link(link)
        except UnicodeError:
            pass
        else:
            if link and link not in links:
                links.append(link)
    return links


def main():
    usage = 'usage: %prog [options] xpath1 [xpath2 ...]'
    parser = OptionParser(usage)
    parser.add_option("-f", "--file", dest="filename", help="read html from FILENAME")
    parser.add_option("-s", "--string", dest="string", help="read html from STRING")
    parser.add_option("-u", "--url", dest="url", help="read html from URL")
    parser.add_option("-d", "--doctest", action="store_true", dest="doctest")
    (options, xpaths) = parser.parse_args()

    if options.doctest:
        import doctest
        return doctest.testmod()
    else:
        if len(xpaths) == 0:
            parser.error('Need atleast 1 xpath')

        if options.filename:
            html = open(options.filename).read()
        elif options.string:
            html = options.string
        elif options.url:
            html = urllib2.urlopen(options.url).read()
        
        results = [search(html, xpath) for xpath in xpaths]
        return results

        
if __name__ == '__main__':
    print main()
