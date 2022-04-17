#!/usr/bin/env python3

import datetime
import ssl
import urllib.parse as parse
import urllib.request
from lxml import html
import json
import sqlite3
import getopt
import re

G_DB_NAME = "wf_mkt_hist.db"
G_DB_ITEMS_NAME = "items"
G_DB_ITEMS_HIST = "hist"
G_WFM_USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.47 Safari/537.36'

def db_setup(db):
    cur = db.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS " + G_DB_ITEMS_NAME + " (name text)")
    cur.execute("CREATE TABLE IF NOT EXISTS " + G_DB_ITEMS_HIST + " (id integer, ts timestamp, volume integer, min integer, max integer, open integer, close integer, avg real, w_avg real, median real, m_avg real)")
    db.commit()
    return None

def db_fetch_names(db, nm):
    cur = db.cursor()
    for i in nm:
        q = "INSERT INTO " + G_DB_ITEMS_NAME + "(name) SELECT '" + i + "' WHERE NOT EXISTS (SELECT 1 FROM " + G_DB_ITEMS_NAME + " WHERE name='" + i + "')";
        cur.execute(q)
    db.commit()
    rv = {}
    ri = cur.execute("SELECT MAX(rowid) as id, name FROM " + G_DB_ITEMS_NAME + " WHERE 1=1 GROUP BY name")
    for i in ri:
        rv[i[1]] = i[0]
    return rv

def db_fetch_ts(db, nm_id):
    cur = db.cursor()
    ri = cur.execute("SELECT ts FROM " + G_DB_ITEMS_HIST + " WHERE 1=1 AND id=? GROUP BY ts", (nm_id,))
    rv = {}
    for i in ri:
        rv[datetime.datetime.fromisoformat(i[0])] = 1
    return rv

def db_insert_raw_data(db, all_data):
    nm_id = db_fetch_names(db, all_data.keys())
    cur = db.cursor()
    rv_stats = {}
    for k, v in all_data.items():
        rv_stats[k] = 0
        # select all dates for given item
        all_ts = db_fetch_ts(db, nm_id[k])
        for r in v:
            if r[0] in all_ts.keys():
                continue
            cur.execute("INSERT INTO " + G_DB_ITEMS_HIST + " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (nm_id[k], r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9]))
            rv_stats[k] = rv_stats[k]+1
    db.commit()
    return rv_stats

def parse_hist_stats(data):
    root = html.fromstring(data)
    # find the hist data section
    hist_data = None
    for x in root.getiterator():
        #print(x.tag, x.attrib) #, x.text, x.tail)
        if x.tag == 'script' and x.attrib.get('type', None) == 'application/json' and x.attrib.get('id', None) == 'application-state':
            hist_data = json.loads(x.text)
            break
    rv = []
    if hist_data is not None:
        for x in hist_data["payload"]["statistics_closed"]["90days"]:
            # skip fully upgraded mods
            if x.get('mod_rank', 0) != 0:
                continue
            rv.append((datetime.datetime.fromisoformat(x['datetime']), int(x['volume']), int(x['min_price']), int(x['max_price']), int(x['open_price']), int(x['closed_price']), float(x['avg_price']), float(x['wa_price']), float(x['median']), float(x['moving_avg'])))
    return rv

def get_wfm_webapi(str_url):
    # ignore certificate - I know it's not great
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(str_url, data=None, headers={'User-Agent': G_WFM_USER_AGENT})
    f = urllib.request.urlopen(req, context=ctx)
    return f.read().decode('utf-8')

def get_hist_stats(item_name):
    str_url = 'https://warframe.market/items/' + item_name.replace(' ', '_').lower() + '/statistics'
    data = get_wfm_webapi(str_url)
    return parse_hist_stats(data)

def store_hist_data(item_names):
    all_items = {}
    for nm in item_names:
        all_items[nm] = get_hist_stats(nm)
    db = sqlite3.connect(G_DB_NAME)
    db_setup(db)
    rv = db_insert_raw_data(db, all_items)
    db.close()
    return rv

def get_items_list(search_nm):
    str_url = 'https://api.warframe.market/v1/items'
    data = get_wfm_webapi(str_url)
    jdata = json.loads(data)
    r_items = []
    for s in search_nm:
        r_items.append(re.compile(r'.*' + re.escape(s.strip()) + r'.*', re.IGNORECASE))
    rv = {}
    for k in jdata['payload']['items']:
        for r_i in r_items:
            if r_i.match(k['item_name']) is not None:
                rv[k['item_name']] = 0
    return list(rv.keys())

def main():
    l_items = get_items_list(['galvanized'])
    print("\tAdding/Updating:")
    for i in l_items:
        print(i)
    rv = store_hist_data(l_items)
    print("\tEntries added:")
    for i in rv:
        print(i, rv[i])

if __name__ == "__main__":
    main()
