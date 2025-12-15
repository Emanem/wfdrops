#!/usr/bin/env python3

import datetime
import urllib3
from lxml import html
import json
import sqlite3
import getopt
import sys
import re
import time
from tkinter import *
from tkinter.ttk import Notebook
from matplotlib.figure import Figure
import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.patches import Rectangle
from matplotlib import cm
from matplotlib import colors
import random

G_DB_NAME = "wf_mkt_hist.db"
G_DB_NAME_RO = "file:" + G_DB_NAME + "?mode=ro"
G_DB_ITEMS_NAME = "items"
G_DB_ITEMS_HIST = "hist"
G_DB_TAGS_NAME = "tags"
G_DB_ITEMS_TAGS = "items_attrs"
G_WFM_USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.47 Safari/537.36'
G_SLEEP_THROTTLE = 0.5
G_N_DAYS_HIST = 365

def uniform_str(s):
    spl = s.split()
    rv = []
    for ts in spl:
        lc = ts.lower()
        rv.append(lc[0].upper() + lc[1:])
    return ' '.join(rv)

# utility function to make the DB names uniform
def update_db_names(db):
    cur = db.cursor()
    q="select name, ROWID from " + G_DB_ITEMS_NAME
    ri = cur.execute(q)
    nm = {}
    for i in ri:
        print(i)
        nm[i[0]] = i[1]
    for k, v in nm.items():
        q = "update " + G_DB_ITEMS_NAME + " set name=? where ROWID=?"
        cur.execute(q, (uniform_str(k), v))
    db.commit()
    return None

def db_setup(db):
    cur = db.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS " + G_DB_ITEMS_NAME + " (name text)")
    cur.execute("CREATE TABLE IF NOT EXISTS " + G_DB_ITEMS_HIST + " (id integer, ts timestamp, volume integer, min integer, max integer, open integer, close integer, avg real, w_avg real, median real, m_avg real)")
    cur.execute("CREATE INDEX IF NOT EXISTS i1 ON " + G_DB_ITEMS_HIST + "(id)")
    cur.execute("CREATE TABLE IF NOT EXISTS " + G_DB_TAGS_NAME + " (name text)")
    cur.execute("CREATE TABLE IF NOT EXISTS " + G_DB_ITEMS_TAGS + " (item_id integer, tag_id integer)")
    db.commit()
    return None

def db_fetch_names(db, tb_nm, nm):
    cur = db.cursor()
    for i in nm:
        q = "INSERT INTO " + tb_nm + "(name) SELECT ? WHERE NOT EXISTS (SELECT 1 FROM " + tb_nm + " WHERE name=?)";
        cur.execute(q, (i, i))
    db.commit()
    rv = {}
    ri = cur.execute("SELECT MAX(rowid) as id, name FROM " + tb_nm + " WHERE 1=1 GROUP BY name")
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

def db_fetch_names_tags(db):
    cur = db.cursor()
    ri = cur.execute("SELECT n.name, COUNT(n.name) as total FROM " + G_DB_ITEMS_NAME + " n JOIN " + G_DB_ITEMS_TAGS + " i ON (n.rowid=i.item_id) GROUP BY n.name")
    rv = {}
    for i in ri:
        rv[i[0]] = i[1]
    return rv

def db_fetch_max_ts(db):
    cur = db.cursor()
    ri = cur.execute("SELECT CAST(JULIANDAY('now') - JULIANDAY(MAX(ts)) as INT) FROM " + G_DB_ITEMS_HIST + " WHERE 1=1")
    for i in ri:
        return i[0]
    return sys.maxsize

def db_insert_raw_data(db, all_data):
    cur_max_ts_interval = db_fetch_max_ts(db)
    nm_id = db_fetch_names(db, G_DB_ITEMS_NAME, all_data.keys())
    cur = db.cursor()
    rv_stats = {}
    for k, v in all_data.items():
        rv_stats[k] = 0
        # select all dates for given item
        # and insert missing dates
        all_ts = db_fetch_ts(db, nm_id[k])
        for r in v[0]:
            if r[0] in all_ts.keys():
                continue
            cur.execute("INSERT INTO " + G_DB_ITEMS_HIST + " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (nm_id[k], r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9]))
            rv_stats[k] = rv_stats[k]+1
        # push all the tags - we're fetching more than
        # required but it's ok for now
        cur_tags = db_fetch_names(db, G_DB_TAGS_NAME, v[1])
        # add the tags for a given item
        for r in v[1]:
            cur.execute("INSERT INTO " + G_DB_ITEMS_TAGS + "(item_id, tag_id) SELECT ?, ? WHERE NOT EXISTS (SELECT 1 FROM " + G_DB_ITEMS_TAGS + " WHERE item_id=? and tag_id=?)", (nm_id[k], cur_tags[r], nm_id[k], cur_tags[r]))
    db.commit()
    return rv_stats, cur_max_ts_interval

def parse_hist_stats(data, item_name):
    hist_data = json.loads(data)
    rv = []
    subytpes_r = [None, 'intact', 'basic', 'small', 'revealed', 'blueprint']
    subtype_found = {}
    if hist_data is not None:
        for x in hist_data["payload"]["statistics_closed"]["90days"]:
            # skip fully upgraded mods
            if x.get('mod_rank', 0) != 0:
                continue
            # check if there's 'cyan_stars' and 'amber_stars' and if so
            # ensure those are 2 and 1 and the name of the item is ayatan*sculpture
            if re.match(r'^ayatan.*sculpture$', item_name, re.IGNORECASE):
                if x.get('cyan_stars', 0) != 2 or x.get('amber_stars', 0) != 1:
                    continue
            # skip non 'intact' relics or fishes
            # use the list for other types
            if x.get('subtype', None) not in subytpes_r:
                subtype_found[x.get('subtype', None)] = 0
                continue
            rv.append((datetime.datetime.fromisoformat(x['datetime']), int(x['volume']), int(x['min_price']), int(x['max_price']), int(x['open_price']), int(x['closed_price']), float(x['avg_price']), float(x['wa_price']), float(x['median']), float(x.get('moving_avg', 0.0))))
    # consistency check
    uniq_dates = {}
    for x in rv:
        uniq_dates[x[0]] = None
    if len(uniq_dates) != len(rv):
        fname = f'{item_name}.json'
        with open(fname, 'w') as f:
            f.write(data)
        raise ValueError(f'Current item may have multiple valid subptypes yielding to duplicate data (json file saved as {fname})')
    return (rv, subtype_found)

def parse_attrs(data):
    jdata = json.loads(data)
    rv = {}
    for y in jdata['data']['tags']:
        rv[y.lower()] = 1
    return list(rv.keys())

def get_wfm_webapi(str_url, https_cp):
    f = https_cp.urlopen('GET', str_url, headers={'User-Agent': G_WFM_USER_AGENT, 'crossplay' : 'true'})
    f.read()
    return f.data.decode('utf-8')

def get_hist_stats(item_name, https_cp, query_metadata):
    # sample api historical data
    # https://api.warframe.market/v2/items/mirage_prime_systems_blueprint/statistics
    str_url = f'https://api.warframe.market/v1/items/{item_name}/statistics'
    data = get_wfm_webapi(str_url, https_cp)
    tags = []
    if query_metadata:
        time.sleep(G_SLEEP_THROTTLE)
        str_url = f'https://api.warframe.market/v2/items/{item_name}'
        data_attrs = get_wfm_webapi(str_url, https_cp)
        tags = parse_attrs(data_attrs)
    phs = parse_hist_stats(data, item_name)
    return (phs[0], tags, phs[1])

def store_hist_data(item_names, force_metadata=False):
    print("\tFetching:")
    all_items = {}
    n_digits = len(str(len(item_names.keys())))
    # have to init the DB connection here
    # to optimize skipping existing tags
    db = sqlite3.connect(G_DB_NAME)
    db_setup(db)
    items_tags = db_fetch_names_tags(db) if not force_metadata else {}
    cnt = 0
    # create the HTTPS pool here
    https_cp = urllib3.HTTPSConnectionPool('api.warframe.market')
    for nm, q_nm in item_names.items():
        cnt += 1
        print("[{count:{fill}{align}{width}}/{total}]".format(count=cnt, total=len(item_names), fill=' ', align='>', width=n_digits), end='\t')
        print(nm, end='...')
        tm_start = time.monotonic()
        try:
            # optimization: only query metadata when we don't have tags
            all_items[nm] = get_hist_stats(q_nm, https_cp, nm not in items_tags)
        except Exception as e:
            print("Error, carrying on (", e, ")")
        else:
            # this is not great - but it does work...
            tm_end = time.monotonic()
            print('done', tm_end-tm_start, 's', "(" + str(len(all_items[nm][0])) + " entries)")
        finally:
            tm_end = time.monotonic()
            sleep_throttle = G_SLEEP_THROTTLE - (tm_end - tm_start)
            if sleep_throttle > 0.0:
                time.sleep(sleep_throttle)
    # perform insertion of all data
    rv, max_ts_interval = db_insert_raw_data(db, all_items)
    db.close()
    # prepare return query stats and
    # warning items
    rv_q = {}
    rv_subtypes = {}
    for nm in all_items.keys():
        rv_q[nm] = len(all_items[nm][0])
        if bool(all_items[nm][2]):
            rv_subtypes[nm] = all_items[nm][2]
    return (rv, rv_q, rv_subtypes, max_ts_interval)

def get_items_list(search_nm, get_all=False):
    str_url = '/v2/items'
    https_cp = urllib3.HTTPSConnectionPool('api.warframe.market')
    data = get_wfm_webapi(str_url, https_cp)
    jdata = json.loads(data)
    if get_all:
        rv = {}
        for k in jdata['data']:
            rv[uniform_str(k['i18n']['en']['name'])] = k['slug']
        return rv
    r_items = []
    for s in search_nm:
        r_items.append(re.compile(r'.*' + re.escape(s.strip()) + r'.*', re.IGNORECASE))
    rv = {}
    for k in jdata['data']:
        for r_i in r_items:
            if r_i.match(k['i18n']['en']['name']) is not None:
                rv[uniform_str(k['i18n']['en']['name'])] = k['slug']
    return rv

def do_extract(search_nm, e_values, *, tags=[], wildcard_ws=False, n_days=G_N_DAYS_HIST):
    query = """
SELECT  i.name as name, h.ts as ts
"""
    values_q = ""
    for v in e_values:
        values_q += ", h." + v + " as " + v
    query += values_q
    query += """
FROM    items i
JOIN    hist h
ON      (i.rowid=h.id)"""
    if tags:
        query_tags = """
JOIN    (
    SELECT  ia.item_id
    FROM    items_attrs ia
    JOIN    tags t
    ON (ia.tag_id=t.rowid)
    WHERE   1=1
    AND     LOWER(t.name) IN ("""
        query_tags += ', '.join(["LOWER('" + x + "')" for x in tags])
        query_tags += """)
    GROUP BY ia.item_id"""
        query_tags += """
    HAVING COUNT(0)>=""" + str(len(tags))
        query_tags += """
) t_ ON (i.rowid=t_.item_id)
"""
        query += query_tags
    query += """WHERE   1=1
AND     (
        1=0
"""
    items_q = ""
    for n in search_nm:
        if wildcard_ws:
            n_v = re.split(r'\s+', n)
            n = '%'.join(n_v)
        items_q += "\tOR i.name LIKE '%" + n + "%'\n"
    # if we have tags do select even if search_nm is empty
    if tags and not search_nm:
        items_q = "\tOR 1=1\n"
    query += items_q
    query += ")"
    if n_days > 0:
        query += """
AND     h.ts > DATE('now', ?)"""
    interval_q = "-" + str(n_days) + " days"
    db = sqlite3.connect(G_DB_NAME_RO, uri=True)
    db_setup(db)
    cur = db.cursor()
    ri = cur.execute(query) if n_days <= 0 else cur.execute(query, (interval_q,))
    rv = {}
    for v in ri:
        cd = datetime.datetime.fromisoformat(v[1])
        ci = v[0]
        if cd not in rv:
            rv[cd] = {}
        if ci not in rv[cd]:
            rv[cd][ci] = {}
        for i in range(len(e_values)):
            rv[cd][ci][e_values[i]] = v[2+i]
    db.close()
    return rv

def do_extract_tags():
    db = sqlite3.connect(G_DB_NAME_RO, uri=True)
    db_setup(db)
    cur = db.cursor()
    ri = cur.execute("SELECT name FROM " + G_DB_TAGS_NAME + " GROUP BY name")
    rv = []
    for v in ri:
        rv.append(v[0])
    db.close()
    filters = ['---']
    return [x for x in rv if (x not in filters)]

def do_summary(n_days=5, min_volume=24, min_price=25, search_nm=[], search_tags=[], tags_andor=True, exclude_sets=True):
    items_q = ""
    for n in search_nm:
        n_v = re.split(r'\s+', n)
        n = '%'.join(n_v)
        items_q += "    OR x.name LIKE '%" + n + "%'\n"
    query = """
select x.name, x.price, x.volume, x.change
from (
    SELECT i.ROWID, i.name, avg(ts_x.price) as price, avg(ts_x.volume) as volume, 100.0 + 100.0*avg((h_max.avg - h_min.avg)/h_min.avg) as 'change'
    FROM	items i
    JOIN	(
        SELECT 	h.id, min(h.ts) as min_ts, max(h.ts) as max_ts, avg(volume) as volume, avg(avg) as price
        FROM	hist h
        WHERE	1=1
        AND		h.ts > DATE('now', ?)
        GROUP BY	h.id
    ) ts_x
    ON		(i.ROWID=ts_x.id)
    JOIN	hist h_min
    ON		(i.ROWID=h_min.id AND h_min.ts=ts_x.min_ts)
    JOIN	hist h_max
    ON		(i.ROWID=h_max.id AND h_max.ts=ts_x.max_ts)
    WHERE	1=1"""
    if exclude_sets:
        query += "    AND   NOT i.name LIKE '%set'"
    query += """
    GROUP BY	i.ROWID, i.name
) x
"""
    if search_tags:
        count_tags = str(len(search_tags)) if tags_andor else '1'
        query_tags = """JOIN    (
    SELECT  ia.item_id
    FROM    items_attrs ia
    JOIN    tags t
    ON (ia.tag_id=t.rowid)
    WHERE   1=1
    AND     LOWER(t.name) IN ("""
        query_tags += ', '.join(["LOWER('" + x + "')" for x in search_tags])
        query_tags += """)
    GROUP BY ia.item_id"""
        query_tags += """
    HAVING COUNT(0)>=""" + count_tags
        query_tags += """
) t_ ON (x.rowid=t_.item_id)
"""
        query += query_tags
    query += """WHERE	1=1
AND		x.volume >= ?
AND		x.price >= ?
AND(
    1=?
"""
    query += items_q
    query += """)
ORDER BY	x.price DESC
"""
    interval_q = "-" + str(n_days) + " days"
    db = sqlite3.connect(G_DB_NAME_RO, uri=True)
    db_setup(db)
    cur = db.cursor()
    flag_search = 1 if len(search_nm) == 0 else 0
    ri = cur.execute(query, (interval_q, min_volume, min_price, flag_search))
    rv = []
    for v in ri:
        rv.append((v[0], v[1], v[2], v[3]))
    db.close()
    return rv

def do_extract_printout(ev, e_values):
    # find all the items we have managed to extract
    all_items = {}
    for k, v in ev.items():
        for i in v.keys():
            all_items[i] = 0
    # first print header
    print("timestamp", end='')
    for i in all_items.keys():
        for v in e_values:
            print("," + i + " [" + v + "]", sep='', end='')
    print()
    # lambda to lookup values
    def lookup_fn(ts, item, val):
        if ts not in ev:
            return None
        if item not in ev[ts]:
            return None
        if val not in ev[ts][item]:
            return None
        return ev[ts][item][val]
    # finally print out everything
    for t in ev.keys():
        print(t, end='')
        for i in all_items.keys():
            for v in e_values:
                val = lookup_fn(t, i, v)
                if val is None:
                    print(",", end='')
                else:
                    print(",", val, sep='', end='')
        print()

class HistWin(Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.graph = None
        self.canvas = None
        self.reset_data()
        self.create_widgets()

    def reset_data(self):
        self.my_item_data = ""
        self.my_x_data = []
        self.my_y1_data = {'min':[], 'avg':[], 'max':[]}
        self.my_y2_data = []

    def search_changed(self, *args):
        v = self.search_val.get()
        if len(v) <= 0:
            self.other_items_val.set("")
            self.reset_data()
            self.update_graph()
            return None
        ev = do_extract([v], ['volume', 'min', 'avg', 'max'], wildcard_ws=True, n_days=G_N_DAYS_HIST)
        # get the first item in alphabetical order
        all_items = {}
        for k, v in ev.items():
            for i in v.keys():
                all_items[i] = 0
        sorted_items = list(all_items.keys())
        sorted_items.sort()
        if not sorted_items:
            self.other_items_val.set("<no suggestions available>")
            self.reset_data()
            self.update_graph()
            return None
        si = sorted_items[0]
        self.other_items_val.set(', '.join(sorted_items)[:2048])
        # extract the time keys only where we have
        # our item
        time_keys = []
        for k, v in ev.items():
            if si in v:
                time_keys.append(k)
        time_keys.sort()
        self.reset_data()
        self.my_item_data = si
        for k in time_keys:
            v = ev[k]
            self.my_x_data.append(k)
            self.my_y1_data['min'].append(v[si]['min'])
            self.my_y1_data['avg'].append(v[si]['avg'])
            self.my_y1_data['max'].append(v[si]['max'])
            self.my_y2_data.append(v[si]['volume'])
        self.update_graph()

    def update_graph(self, w=0, h=0):
        if (w == 0) or (h == 0):
            w = self.master.winfo_width()
            h = self.master.winfo_height()
        dpi = 100
        g_w = (w-20)
        g_h = (h-self.graph_start_y-35)
        if not self.graph:
            self.graph = Figure(figsize=(g_w/dpi, g_h/dpi), dpi=100)
        self.graph.clear()
        if self.my_x_data:
            sp = self.graph.add_subplot(111)
            sp.set_ylabel('Price', color="red")
            sp.set_title(self.my_item_data)
            sp.axhline(y=self.my_y1_data['avg'][-1], color=[0.75, 0.5, 0.5], linestyle=':')
            sp.plot(self.my_x_data, self.my_y1_data['min'], color=[1, 0, 0])
            sp.plot(self.my_x_data, self.my_y1_data['avg'], color=[1, 0.5, 0.5])
            sp.plot(self.my_x_data, self.my_y1_data['max'], color=[1, 0.75, 0.75])
            sp2 = sp.twinx()
            sp2.bar(self.my_x_data, self.my_y2_data, color=[0, 0, 1, 0.3])
            sp2.set_ylabel('Volume', color="blue")
            sp.set_xlim(min(self.my_x_data), max(self.my_x_data))
            sp.set_ylim(ymin=0)
            for l in sp.get_xticklabels():
                l.set_rotation(25)
                l.set_horizontalalignment('right')
        if self.canvas is None:
            self.canvas = FigureCanvasTkAgg(self.graph, master=self)
        self.canvas.draw()
        self.canvas.get_tk_widget().place(x=10, y=self.graph_start_y, width=g_w, height=g_h)

    def do_resize(self, w, h):
        oc_w = w - self.other_items.winfo_x() - 20
        self.other_items.place(width=oc_w)
        self.config(width=w, height=h)
        self.update_graph(w, h)
        self.config(width=w, height=h)

    def create_widgets(self):
        y_plc = 10
        # Label - "Search for item:"
        self.label_top = Label(self, text="Single item:", anchor=W)
        self.label_top.place(x=10, y=y_plc, width=128, height=24)
        # Entry to execute the search
        self.search_val = StringVar()
        self.search_val.trace_add("write", self.search_changed)
        self.search_entry = Entry(self, textvariable=self.search_val)
        self.search_entry.place(x=138, y=y_plc, width=128, height=24)
        # Label to display the other choices
        # don't care about width, we sort it out in 'on_resize'
        self.other_items_val = StringVar()
        self.other_items = Label(self, textvariable=self.other_items_val, anchor=W)
        self.other_items.place(x=138+128+10, y=y_plc, height=24)
        y_plc += 24+10
        self.graph_start_y = y_plc

# values has to be a list of dictionaries of the form {'id':<string>, 'value':<float>}
def treemap_plot(values, tl = {'x':0.0, 'y':0.0}, br = {'x':1.0, 'y':1.0}, split_x=True):
    if 0 == len(values):
        return []
    if 1 == len(values):
        return [{'id':values[0]['id'], 'tl':tl, 'br':br, 'value':values[0]['value']}]
    else:
        # recursive step, splitting the list in 2
        split_s = len(values) // 2
        v_left = values[:split_s]
        v_right = values[split_s:]
        v_left_sum = sum([x['value'] for x in v_left])
        v_right_sum = sum([x['value'] for x in v_right])
        w_left = v_left_sum/(v_left_sum + v_right_sum)
        n_br = {}
        if split_x:
            x_sz = br['x'] - tl['x']
            new_x = tl['x'] + x_sz*w_left
            n_br['x'] = new_x
            n_br['y'] = br['y']
        else:
            y_sz = br['y'] - tl['y']
            new_y = tl['y'] + y_sz*w_left
            n_br['x'] = br['x']
            n_br['y'] = new_y
        next_split_x = not split_x
        if split_x:
            rv_left = treemap_plot(v_left, tl, n_br, next_split_x)
            rv_right = treemap_plot(v_right, {'x':n_br['x'], 'y':tl['y']}, br, next_split_x)
        else:
            rv_left = treemap_plot(v_left, tl, n_br, next_split_x)
            rv_right = treemap_plot(v_right, {'x':tl['x'], 'y':n_br['y']}, br, next_split_x)
        return rv_left + rv_right

# draw a treemap (tm) obtained via treemap_plot and an axis (ax) via
# matplotlib figure <Figure>.add_subplot(...)
def treemap_draw(tm, ax, *, color_fn=None):
    #draw a fake line, fully transparent
    ax.plot([0, 1], [0, 1], color=[1, 1, 1, 0])
    ax.set_axis_off()
    # for consistent colours
    if not color_fn:
        random.seed(a="123")
    for el in tm:
        r_color = (random.random(), random.random(), random.random()) if not color_fn else color_fn(el['value'])
        r = Rectangle((el['tl']['x'], el['tl']['y']), el['br']['x']-el['tl']['x'], el['br']['y']-el['tl']['y'], facecolor=r_color)
        ax.add_patch(r)
        rx, ry = r.get_xy()
        cx = rx + r.get_width()/2.0
        cy = ry + r.get_height()/2.0
        ax.annotate(el['id'], (cx, cy), ha='center', va='center')

class TagsPicker(Frame):
    def __init__(self, master, treemap):
        super().__init__(master)
        self.tags = do_extract_tags()
        self.tm = treemap
        self.tm.btn_tags['state'] = DISABLED
        self.andor_v = IntVar()
        self.andor_v.set(1 if self.tm.tags_andor else 2)
        self.create_widgets()
        self.master.protocol("WM_DELETE_WINDOW", self.on_cancel)
        master.title("Select Tags")
        self.pack(expand=Y, fill=Y)

    def on_apply(self):
        self.tm.tags = [self.tags[x] for x in self.lb.curselection()]
        self.tm.tags_andor = self.andor_v.get() == 1
        self.tm.search_changed()
        self.tm.btn_tags['state'] = NORMAL
        self.master.destroy()

    def on_cancel(self):
        self.tm.btn_tags['state'] = NORMAL
        self.master.destroy()

    def create_widgets(self):
        self.sel_fr = Frame(self)
        self.sel_fr.pack(padx = 10, pady = 10, expand = YES, fill = "both")
        self.ysb = Scrollbar(self.sel_fr)
        self.ysb.pack(side = RIGHT, fill = Y)
        #
        self.lb = Listbox(self.sel_fr, selectmode="multiple", yscrollcommand = self.ysb.set)
        self.lb.pack(expand = YES, fill = "both")
        for i in range(len(self.tags)):
            self.lb.insert(END, self.tags[i])
            if self.tags[i] in self.tm.tags:
                self.lb.selection_set(i)
        self.ysb.config(command = self.lb.yview)
        #
        self.sel_fr_andor = Frame(self)
        self.sel_fr_andor.pack(padx = 10, pady = 10, fill = "both")
        self.rdb_and = Radiobutton(self.sel_fr_andor, text="AND", padx = 20, variable=self.andor_v, value=1).pack(side = LEFT)
        self.rdb_or = Radiobutton(self.sel_fr_andor, text="OR", padx = 20, variable=self.andor_v, value=2).pack(side = RIGHT)
        self.sel_fr_b = Frame(self)
        self.sel_fr_b.pack(padx = 10, pady = 10, fill = "both")
        self.btn_apply = Button(self.sel_fr_b, text="Apply", command=self.on_apply)
        self.btn_apply.pack(side = LEFT)
        self.btn_cancel = Button(self.sel_fr_b, text="Cancel", command=self.on_cancel)
        self.btn_cancel.pack(side = RIGHT)

class TreeMapWin(Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.graph = None
        self.canvas = None
        self.tags = []
        self.tags_andor = True
        self.min_value = 0.0
        self.max_value = 1.0
        self.min_color = (0.5, 0.5, 1.0)
        self.max_color = (1.0, 1.0, 0.5)
        self.reset_data()
        self.create_widgets()

    def get_color(self, cur_value):
        sf = 0.5
        if (self.max_value - self.min_value) != 0.0:
            sf = 1.0 - (self.max_value - cur_value)/(self.max_value - self.min_value)
        r_sf = []
        for i in range(3):
            r_sf.append(self.min_color[i] + (self.max_color[i] - self.min_color[i])*sf)
        return (r_sf[0], r_sf[1], r_sf[2])

    def reset_data(self):
        # this should be in the form of [{'id':'val1', 'value':1.0}, {'id':'val2', 'value':0.5}, {'id':'val3', 'value':0.4}]
        self.my_tm_data = []

    def btn_tags(self):
        root = Toplevel()
        tp = TagsPicker(root, self)

    def search_changed(self, *args):
        v = self.search_val.get()
        if len(v.strip()) < 3 and not self.tags:
            self.other_items_val.set("")
            self.reset_data()
            self.update_graph()
            return None
        items = [x for x in v.split(',') if len(x) > 0]
        ev = do_summary(min_volume=0, min_price=0, search_nm=items, search_tags=self.tags, tags_andor=self.tags_andor, exclude_sets=False)
        # get the first item in alphabetical order
        ev.sort()
        if not ev:
            self.other_items_val.set("<no suggestions available>")
            self.reset_data()
            self.update_graph()
            return None
        self.other_items_val.set(', '.join([x[0] for x in ev])[:2048])
        self.reset_data()
        for e in ev:
            self.my_tm_data.append({'id':e[0], 'value':(e[1] if self.graph_type.get() == "Price" else e[2] if self.graph_type.get() == "Volume" else e[3])})
        self.update_graph()

    def update_graph(self, w=0, h=0):
        if (w == 0) or (h == 0):
            w = self.master.winfo_width()
            h = self.master.winfo_height()
        dpi = 100
        g_w = (w-20)
        g_h = (h-self.graph_start_y-35)
        if not self.graph:
            self.graph = Figure(figsize=(g_w/dpi, g_h/dpi), dpi=100)
        self.graph.clear()
        if self.my_tm_data:
            ax = self.graph.add_subplot(111)
            my_vals = [x['value'] for x in self.my_tm_data]
            self.min_value = min(my_vals)
            self.max_value = max(my_vals)
            treemap_draw(treemap_plot(self.my_tm_data), ax, color_fn=self.get_color)
            if self.tags:
                ax.set_title("Tags: " + ', '.join(self.tags))
            colmap = cm.ScalarMappable(cmap=colors.LinearSegmentedColormap.from_list("", [self.min_color, self.max_color]))
            colmap.set_clim(vmin=self.min_value, vmax=self.max_value)
            self.graph.colorbar(colmap, orientation='vertical', fraction=0.02, pad=0, aspect=60)
        if self.canvas is None:
            self.canvas = FigureCanvasTkAgg(self.graph, master=self)
        self.canvas.draw()
        self.canvas.get_tk_widget().place(x=10, y=self.graph_start_y, width=g_w, height=g_h)

    def do_resize(self, w, h):
        oc_w = w - self.other_items.winfo_x() - self.gtype_menu.winfo_width() - 30 - self.btn_tags.winfo_width()
        self.other_items.place(width=oc_w)
        # volume w. checkbox on the right hand side
        vw_x = w - 10 - self.gtype_menu.winfo_width() - 10 - self.btn_tags.winfo_width()
        self.gtype_menu.place(x=vw_x)
        # tag button on the rightmost side
        tagb_x = w - 10 - self.btn_tags.winfo_width()
        self.btn_tags.place(x=tagb_x)
        # update graph
        self.update_graph(w, h)
        self.config(width=w, height=h)

    def create_widgets(self):
        y_plc = 10
        # Label - "Search for item:"
        self.label_top = Label(self, text="Multiple items:", anchor=W)
        self.label_top.place(x=10, y=y_plc, width=128, height=24)
        # Entry to execute the search
        self.search_val = StringVar()
        self.search_val.trace_add("write", self.search_changed)
        self.search_entry = Entry(self, textvariable=self.search_val)
        self.search_entry.place(x=138, y=y_plc, width=128, height=24)
        # Label to display the other choices
        # don't care about width, we sort it out in 'on_resize'
        self.other_items_val = StringVar()
        self.other_items = Label(self, textvariable=self.other_items_val, anchor=W)
        self.other_items.place(x=138+128+10, y=y_plc, height=24)
        # values for the volume weight in the results
        self.graph_type = StringVar()
        self.graph_type.set("Price")
        self.graph_type.trace("w", self.search_changed)
        self.gtype_menu = OptionMenu(self, self.graph_type, "Price", "Volume", "Price Chng %")
        self.gtype_menu.place(y=y_plc, width=128, height=24)
        # button to display pop-up to set tags
        self.btn_tags = Button(self, text="Select tags", command=self.btn_tags)
        self.btn_tags.place(y=y_plc, height=24)
        y_plc += 24+10
        self.graph_start_y = y_plc

class MainWin(Notebook):
    def __init__(self, master=None):
        super().__init__(master)
        self.master.title("WF Market Hist")
        self.master.myId = 1
        self.master.bind("<Configure>", self.on_resize)
        self.master.bind_all('<KeyPress>', self.on_key_press)
        self.my_w = 0
        self.my_h = 0
        self.hist_frame = None
        self.treemap_frame = None
        self.resize_scheduled = False
        self.create_widgets()
        self.pack()

    def do_resize(self):
        self.resize_scheduled = False
        if self.hist_frame:
            self.hist_frame.do_resize(self.my_w, self.my_h)
        if self.treemap_frame:
            self.treemap_frame.do_resize(self.my_w, self.my_h)

    def on_key_press(self, event):
        if event.keysym == 'Escape':
            self.master.destroy()

    def on_resize(self, event):
        is_main_window = hasattr(event.widget, 'myId') and (event.widget.myId == 1)
        main_changed_size = is_main_window and ((event.width != self.my_w) or (event.height != self.my_h))
        if main_changed_size:
            # we user 'after' to avoid too many 'resize'
            # events and use too many CPU cycles
            # the delay is going to be 250 ms
            if not self.resize_scheduled:
                self.resize_scheduled = True
                self.after(250, self.do_resize)
            self.my_w = event.width
            self.my_h = event.height

    def create_widgets(self):
        self.hist_frame = HistWin(self)
        self.treemap_frame = TreeMapWin(self)
        self.add(self.hist_frame, text="Historical View")
        self.add(self.treemap_frame, text="TreeMap View")

def display_graphs():
    root = Tk()
    root.minsize(640, 480)
    root.geometry("640x480")
    app = MainWin(master=root)
    app.mainloop()
    return None

def main():
    try:
        opts, args = getopt.getopt(sys.argv[1:], "gueshx", ["show-tags", "tags=", "force-tags", "update-detail", "update-all", "graphs", "update", "extract", "summary", "summary-days=", "summary-any", "search", "help", "values=", "missing", "no-hist-limit", "x-all", "throttle="])
    except getopt.GetoptError as err:
        print(err)
        sys.exit(-1)
    exec_mode = 'u'
    extract_values = ['volume', 'min', 'max', 'open', 'close', 'avg', 'w_avg', 'median', 'm_avg']
    s_n_days = 5
    s_min_volume = 10
    s_min_price = 10
    update_all = False
    update_detail = False
    force_tags = False
    tags = []
    do_summary_sets = False
    for o, a in opts:
        if o in ("-g", "--graphs"):
            exec_mode = 'g'
        elif o in("--no-hist-limit"):
            global G_N_DAYS_HIST
            G_N_DAYS_HIST = 0
        elif o in ("-u", "--update"):
            exec_mode = 'u'
        elif o in ("--update-all"):
            exec_mode = 'u'
            update_all = True
        elif o in ("--update-detail"):
            update_detail = True
        elif o in ("--force-tags"):
            force_tags = True
        elif o in ("-e", "--extract"):
            exec_mode = 'e'
        elif o in ("--tags"):
            tags = a.split(",")
        elif o in ("--show-tags"):
            exec_mode = 't'
        elif o in ("-s", "--search"):
            exec_mode = 's'
        elif o in ("-h", "--help"):
            print(sys.argv[0], "Update and/or Extract Warframe Market historic price data")
            print('''
Usage: (options) item1, item2, ...

-g, --graphs    Display a Tkinter UI with a search pane and graphs of
                a given item, min/avg/max and the volume

--no-hist-limit Removes the 1-year period limit when extracting historical
                values from the DB

-u, --update    Add/update the given items to the local SQLite database
                This is the default operation mode

--update-all    Add/updates all the possible items to the local SQLite
                database - run this sparingly

--update-detail Print individual item timeseries details when updating.
                By default this is off.

--force-tags    Force querying for items metadata even if already stored (it
                should rarely change)

-e, --extract   Extract historic price data for the given items from the
                local SQLite database

--values v1,..  Specify which price item values to be extracted; by default
                all below values would be extracted
                - volume
                - min
                - max
                - open
                - close
                - avg
                - w_avg
                - median
                - m_avg
                Specifying any value using this option implies option '-e'

--tags t1,...   Specify which tags to be extracted; tags are dynamic; to show
                what tags are available, please run with '--show-tags'
                Setting this option doesn't imply not '-e' nor '-x'

--show-tags     Shows available tags and quits

-s, --search    Search remote warframe market for given items

-x, --summary   Quickly print a summary of averaged volumes, avg prices and % price
                changes on the last 5 days from today, ordered by min price 
                descending (no other input paramater needed, would be ignored)
                By default only items whose average volume >= 10 and average
                min price >= 10 will be reported

--x-all         As per above '-x' but also includes 'sets'

--summary-days  Specifies how many days of interval have to be chosen when
                printing out the summary (default 10)
                Specifying any value using this option implies option '-x'

--summary-any   Specifies a flag to report all the items from -x/--summary, thus
                removing the constraints regarding min daily volume and average min
                price (24 and 25 respectively)
                Specifying any value using this option implies option '-x'

--missing       Prints the missing names from the market (i.e. names we have in
                local DB but not anymore in the market)

--throttle t    Sets the sleep throttle when querying WarFrame Market (by default
                0.5 s)

-h, --help      Displays this help and exit
            ''')
            sys.exit(0)
        elif o in ("--values"):
            exec_mode = 'e'
            s_e_values = a.split(",")
            for s in s_e_values:
                if s not in extract_values:
                    print("Invalid value '" + s + "' specified in extraction")
                    sys.exit(-1)
            extract_values = s_e_values
        elif o in ("-x", "--summary", "--x-all"):
            exec_mode = 'm'
            if o == "--x-all":
                do_summary_sets = True
        elif o in ("--summary-days"):
            exec_mode = 'm'
            s_n_days = int(a)
            if s_n_days <= 0:
                print("Invalid number of days '" + a + "' specified, must be > 0")
                sys.exit(-1)
        elif o in ("--summary-any"):
            exec_mode = 'm'
            s_min_volume = 0
            s_min_price = 0
        elif o in ("--missing"):
            exec_mode = 'i'
        elif o in ("--throttle"):
            global G_SLEEP_THROTTLE
            G_SLEEP_THROTTLE = float(a)
    # args should contain the list of items to extract/update
    if exec_mode == 'g':
        display_graphs()
    elif exec_mode == 'u':
        items = get_items_list(args, get_all=update_all)
        print("\tAdding/Updating:")
        for i in items.keys():
            print(i)
        rv, rv_q, rv_subt, max_ts_interval = store_hist_data(items, force_tags)
        if update_detail:
            print("\tEntries added:")
            for i in rv:
                if rv[i] > 0:
                    print(i, rv[i])
        print("\tSummary count hist:")
        dist = {}
        rv_w = {}
        for k, v in rv_q.items():
            if v not in dist:
                dist[v] = 0
            dist[v] = dist[v] + 1
            # we ask for 90 days, if it's
            # more than that, print a warning
            if (v > 89):
                rv_w[k] = v
        for i in sorted(dist):
            print(i, "->", dist[i])
        print("\tSummary count added:")
        dist = {}
        for k, v in rv.items():
            if v not in dist:
                dist[v] = 0
            dist[v] = dist[v] + 1
            # this is also true if an item
            # suddenly has a longer history since
            # we run the latest update
            if (v >= max_ts_interval):
                rv_w[k] = v
        for i in sorted(dist):
            print(i, "->", dist[i])
        # check if we have to print any warning
        # and skipped subtypes
        if bool(rv_w):
            print("\tWarnings:")
            for i in sorted(rv_w):
                print(i, "->", rv_w[i])
        if bool(rv_subt):
            rv_stypes = {}
            for k, v in rv_subt.items():
                for s in v:
                    if s not in rv_stypes:
                        rv_stypes[s] = []
                    rv_stypes[s].append(k)
            print("\tSubtypes skipped:")
            for i in sorted(rv_stypes):
                rv_stypes[i].sort()
                print(i, "->", rv_stypes[i])
    elif exec_mode == 'e':
        ev = do_extract(args, extract_values, tags=tags, n_days=G_N_DAYS_HIST)
        do_extract_printout(ev, extract_values)
    elif exec_mode == 's':
        l_items = get_items_list(args)
        print("\tSearch:")
        for i in l_items.keys():
            print(i)
    elif exec_mode == 'm':
        rv = do_summary(n_days=s_n_days, min_volume=s_min_volume, min_price=s_min_price, search_nm=args, search_tags=tags, exclude_sets=not do_summary_sets)
        print("name,avg price,avg volume,price change %")
        for v in rv:
            print(v[0], v[1], v[2], v[3], sep=',')
    elif exec_mode == 't':
        ev = do_extract_tags()
        print("\tTags:")
        for t in ev:
            print(t)
    elif exec_mode == 'i':
        db = sqlite3.connect(G_DB_NAME_RO, uri=True)
        db_setup(db)
        lcl_nm = db_fetch_names(db, G_DB_ITEMS_NAME, [])
        db.close()
        mkt_nm = get_items_list(None, True)
        print("\tMissing:")
        for n in lcl_nm:
            if n not in mkt_nm:
                print(n)

if __name__ == "__main__":
    # create the HTTPS pool here
    #https_cp = urllib3.HTTPSConnectionPool('api.warframe.market')
    #r = get_hist_stats('arcane_persistence', https_cp, True)
    #print(r)
    main()
