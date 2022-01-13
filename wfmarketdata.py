#!/usr/bin/env python3

import urllib.parse as parse
import urllib.request
from urllib.request import urlopen as req_url
import json
import sqlite3
import time
import getopt
import sys
import re

# Extract all the sell of online players
def getsell(orders):
    ret = []
    for o in orders:
        if(o["order_type"] != "sell"):
            continue
        if(o["user"]["status"] != "ingame"):
            continue
        if(o["platform"] != "pc"):
            continue
        vals = (o["platinum"], o["quantity"], o["user"]["ingame_name"])
        ret.append(vals)
    return sorted(ret, key=lambda x: x[0])

# Search API for most recent average price scrape
def getquotes(search):
    main_url = req_url('https://api.warframe.market/v1/items/' + search.replace(' ', '_') + '/orders')
    data = main_url.read()
    parsed = json.loads(data)
    return getsell(parsed["payload"]["orders"])

# Ensure a normalized table of strings is properly initialized and setup
# returns the k/v pair
def add_all_strings(db, nm, tab_name):
    cur = db.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS " + tab_name + " (v text)")
    for i in nm:
        q = "INSERT INTO " + tab_name + "(v) SELECT '" + i + "' WHERE NOT EXISTS (SELECT 1 FROM " + tab_name + " WHERE v='" + i + "')";
        cur.execute(q)
    db.commit()
    rv = {}
    ri = cur.execute("SELECT MAX(rowid) as id, v FROM " + tab_name + " WHERE 1=1 GROUP BY v")
    for i in ri:
        rv[i[1]] = i[0]
    return rv

# store in SQL DB
def storesql(con, aq):
    cur = con.cursor()
    # add the 'now' string
    cdt = cur.execute("SELECT datetime('now')")
    for i in cdt:
        dt = i[0]
    r_ts = add_all_strings(con, [dt], "ts_value")
    # add all the items
    r_item = add_all_strings(con, list(aq.keys()), "item_value")
    # then main table
    cur.execute("CREATE TABLE IF NOT EXISTS wf_items (ts integer, item integer, plat integer, qty integer, user text)")
    for k, v in aq.items():
        for i in v:
            cur.execute("INSERT INTO wf_items VALUES(?, ?, ?, ?, ?)", (r_ts[dt], r_item[k], i[0], i[1], i[2]))
    con.commit()

# all the pieces and wf I'm tracking
# should go into a list
wf_parts = [
    "systems",
    "neuroptics",
    "blueprint",
    "chassis",
]

wf_names = [
    "mirage",
    "rhino",
    "mag",
    "nova",
    "limbo",
    "trinity",
    "mesa",
    "hydroid",
    "volt",
    "loki",
    "vauban",
    "ash",
    "oberon",
    "nekros",
    "valkyr",
    "saryn",
    "ember",
    "frost",
]

# do extract and print to std out
def doextract(con, items):
    r_items = []
    for s in items.split(","):
        r_items.append(re.compile(r'.*' + re.escape(s.strip()) + r'.*', re.IGNORECASE))
    cur = con.cursor()
    citems = cur.execute("SELECT t.v as ts, i.v as item, MIN(w.plat) as plat FROM wf_items w JOIN ts_value t ON (t.rowid=w.ts) JOIN item_value i ON (i.rowid=w.item) GROUP BY i.v, t.v")
    alldata = {}
    allitems = {}
    for i in citems:
        if alldata.get(i[0]) is None:
            alldata[i[0]] = {}
        alldata[i[0]][i[1]] = i[2]
        allitems[i[1]] = 1
    # select required items
    itemsarr = []
    if not r_items:
        itemsarr = allitems.keys()
    else:
        for ci in allitems.keys():
            for r in r_items:
                if r.match(ci) is not None:
                    itemsarr.append(ci)
                    break
    # now print all
    # first header
    print("Timestamp", sep='', end='')
    for k in itemsarr:
        print(",", k, sep='', end='')
    print('')
    # then all data
    for k, v in alldata.items():
        print(k, end='')
        for i in itemsarr:
            if v.get(i) is None:
                print(",", end='')
            else:
                print(",", v[i], sep='', end='')
        print('')
    return None

# do averages extract and print to std out
def doavgextract(con, items):
    r_items = []
    for s in items.split(","):
        r_items.append(re.compile(r'.*' + re.escape(s.strip()) + r'.*', re.IGNORECASE))
    cur = con.cursor()
    alldata = {}
    allitems = {}
    periods = [1, 3, 7, 10, 14, 28, 180]
    # iterate through periods
    for p in periods:
        q = """
SELECT i.v AS 'item', AVG(plat) AS 'plat'
FROM (
	SELECT	ts, item, MIN(plat) as 'plat'
	FROM	wf_items
	GROUP BY ts, item
) x
JOIN ts_value t
ON (x.ts=t.ROWID)
JOIN item_value i
ON (x.item = i.ROWID)
WHERE 1=1
AND t.v >= datetime('now', '-{period:d} day')
AND t.v <= datetime('now')
GROUP BY x.item
        """
        citems = cur.execute(q.format(period=p))
        alldata[p] = {}
        for i in citems:
            alldata[p][i[0]] = i[1]
            allitems[i[0]] = 1
    # select required items
    itemsarr = []
    if not r_items:
        itemsarr = allitems.keys()
    else:
        for ci in allitems.keys():
            for r in r_items:
                if r.match(ci) is not None:
                    itemsarr.append(ci)
                    break
    # now print all
    # first header
    print("Avg Period", sep='', end='')
    for k in itemsarr:
        print(",", k, sep='', end='')
    print('')
    # then all data
    for k, v in alldata.items():
        print(k, end='')
        for i in itemsarr:
            if v.get(i) is None:
                print(",", end='')
            else:
                print(",", v[i], sep='', end='')
        print('')
    return None


# get full list of wf items/parts
def getwfitems():
    ret = []
    for n in wf_names:
        for p in wf_parts:
            ret.append(n + " prime " + p)
    return ret

def main():
    try:
        opts, args = getopt.getopt(sys.argv[1:], "aei:", ["avg-extract", "extract-all", "items="])
    except getopt.GetoptError as err:
        print(err)
        sys.exit(-1)
    extract = False
    avg_extract = False
    items = ""
    for o, a in opts:
        if o in ("-e", "--extract-all"):
            extract = True
        elif o in ("-i", "--items"):
            items = a
            if (not extract):
                extract = True
        elif o in ("-a", "--avg-extract"):
            avg_extract = True
            if (not extract):
                extract = True
        else:
            assert False, "unhandled option"
    # if we're in extract mode just extract, print and quit
    if extract:
        con = sqlite3.connect('wf_items_ext.db')
        if avg_extract:
            doavgextract(con, items)
        else:
            doextract(con, items)
        con.close()
        sys.exit(0)
    # 1 get all the quotes
    aq = {}
    for i in getwfitems():
        print("Getting data for '", i, "'...", sep='')
        aq[i] = getquotes(i)
        time.sleep(0.25)
    # 2 print all
    print(aq)
    # 3 open sql DB and insert data
    con = sqlite3.connect('wf_items_ext.db')
    storesql(con, aq)
    con.close()

if __name__ == "__main__":
    main()
