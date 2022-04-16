#!/usr/bin/env python3

import urllib.parse as parse
import urllib.request
from lxml import html
import json
import time
import getopt
import sys
import re

def parse_hist_stats(data):
    root = html.fromstring(data)
    # find the hist data section
    hist_data = None
    for x in root.getiterator():
        #print(x.tag, x.attrib) #, x.text, x.tail)
        if x.tag == 'script' and x.attrib.get('type', None) == 'application/json' and x.attrib.get('id', None) == 'application-state':
            hist_data = json.loads(x.text)
            break
    if hist_data is not None:
        for x in hist_data["payload"]["statistics_closed"]["90days"]:
            print(x)
            #print(hist_data["payload"][x])
    return None

def get_hist_stats(item_name):
    str_url = 'https://warframe.market/items/' + item_name.replace(' ', '_').lower() + '/statistics'
    req = urllib.request.Request(str_url, data=None, headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.47 Safari/537.36'})
    f = urllib.request.urlopen(req)
    data = f.read().decode('utf-8')
    return parse_hist_stats(data)

def main():
    #get_hist_stats("Galvanized Acceleration");
    with open('out.html', 'r') as f:
        data = f.read()
    parse_hist_stats(data)

if __name__ == "__main__":
    main()
