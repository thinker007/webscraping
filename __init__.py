__doc__ = """
Description: webscraping library
Website: http://code.google.com/p/webscraping/
License: LGPL
"""

__all__ = ['adt', 'alg', 'common', 'download', 'pdict', 'settings', 'webkit', 'xpath']


if __name__ == '__main__':
    import doctest
    for name in __all__:
        module = __import__(name)
        print name
        print doctest.testmod(module)
