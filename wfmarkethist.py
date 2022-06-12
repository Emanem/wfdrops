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
import random
import math

G_DB_NAME = "wf_mkt_hist.db"
G_DB_ITEMS_NAME = "items"
G_DB_ITEMS_HIST = "hist"
G_DB_TAGS_NAME = "tags"
G_DB_ITEMS_TAGS = "items_attrs"
G_WFM_USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.47 Safari/537.36'
G_SLEEP_THROTTLE = 0.5

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

def db_insert_raw_data(db, all_data):
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
            rv.append((datetime.datetime.fromisoformat(x['datetime']), int(x['volume']), int(x['min_price']), int(x['max_price']), int(x['open_price']), int(x['closed_price']), float(x['avg_price']), float(x['wa_price']), float(x['median']), float(x.get('moving_avg', 0.0))))
    return rv

def parse_attrs(data):
    jdata = json.loads(data)
    rv = {}
    for x in jdata['payload']['item']['items_in_set']:
        for y in x['tags']:
            rv[y] = 1
    return list(rv.keys())

def get_wfm_webapi(str_url, https_cp):
    f = https_cp.urlopen('GET', str_url, headers={'User-Agent': G_WFM_USER_AGENT})
    return f.data.decode('utf-8')

def get_hist_stats(item_name, https_cp, https_cp_api, query_metadata):
    str_url = '/items/' + item_name + '/statistics'
    data = get_wfm_webapi(str_url, https_cp)
    tags = []
    if query_metadata:
        time.sleep(G_SLEEP_THROTTLE)
        str_url = '/v1/items/' + item_name
        data_attrs = get_wfm_webapi(str_url, https_cp_api)
        tags = parse_attrs(data_attrs)
    return (parse_hist_stats(data), tags)

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
    https_cp = urllib3.HTTPSConnectionPool('warframe.market')
    https_cp_api = urllib3.HTTPSConnectionPool('api.warframe.market')
    for nm, q_nm in item_names.items():
        cnt += 1
        print("[{count:{fill}{align}{width}}/{total}]".format(count=cnt, total=len(item_names), fill=' ', align='>', width=n_digits), end='\t')
        print(nm, end='...')
        tm_start = time.monotonic()
        try:
            # optimization: only query metadata when we don't have tags
            all_items[nm] = get_hist_stats(q_nm, https_cp, https_cp_api, nm not in items_tags)
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
    rv = db_insert_raw_data(db, all_items)
    db.close()
    return rv

def get_items_list(search_nm, get_all=False):
    str_url = '/v1/items'
    https_cp = urllib3.HTTPSConnectionPool('api.warframe.market')
    data = get_wfm_webapi(str_url, https_cp)
    jdata = json.loads(data)
    if get_all:
        rv = {}
        for k in jdata['payload']['items']:
            rv[k['item_name']] = k['url_name']
        return rv
    r_items = []
    for s in search_nm:
        r_items.append(re.compile(r'.*' + re.escape(s.strip()) + r'.*', re.IGNORECASE))
    rv = {}
    for k in jdata['payload']['items']:
        for r_i in r_items:
            if r_i.match(k['item_name']) is not None:
                rv[k['item_name']] = k['url_name']
    return rv

def do_extract(search_nm, e_values, tags=[], wildcard_ws=False):
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
    db = sqlite3.connect(G_DB_NAME)
    db_setup(db)
    cur = db.cursor()
    ri = cur.execute(query)
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
    db = sqlite3.connect(G_DB_NAME)
    db_setup(db)
    cur = db.cursor()
    ri = cur.execute("SELECT name FROM " + G_DB_TAGS_NAME + " GROUP BY name")
    rv = []
    for v in ri:
        rv.append(v[0])
    db.close()
    return rv

def do_summary(n_days=10, min_volume=24, min_price=25, search_nm=[], search_tags=[]):
    items_q = ""
    for n in search_nm:
        n_v = re.split(r'\s+', n)
        n = '%'.join(n_v)
        items_q += "\tOR x.name LIKE '%" + n + "%'\n"
    query = """
select x.name, x.a_min, x.a_max, x.a_vol
from (
	select 	i.ROWID, i.name, avg(volume) as a_vol, avg(min) as a_min, avg(max) as a_max
	FROM	items i
	JOIN	hist h
	ON		(i.ROWID=h.id)
	WHERE	1=1
	AND		h.ts > DATE('now', ?)
	AND		NOT i.name LIKE '%set'
	GROUP BY	i.ROWID, i.name
) x"""
    if search_tags:
        query_tags = """
JOIN    (
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
    HAVING COUNT(0)>=""" + str(len(search_tags))
        query_tags += """
) t_ ON (x.rowid=t_.item_id)
"""
        query += query_tags
    query += """WHERE	1=1
AND		x.a_vol >= ?
AND		x.a_min >= ?
AND(
    1=?
"""
    query += items_q
    query += """)
ORDER BY	x.a_min DESC
"""
    interval_q = "-" + str(n_days) + " days"
    db = sqlite3.connect(G_DB_NAME)
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
        ev = do_extract([v], ['volume', 'min', 'avg', 'max'], True)
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
        self.my_item_data = si
        self.other_items_val.set(', '.join(sorted_items)[:2048])
        # extract the time keys only where we have
        # our item
        time_keys = []
        for k, v in ev.items():
            if si in v:
                time_keys.append(k)
        time_keys.sort()
        self.reset_data()
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
        else:
            self.graph.clear()
            self.graph.set_figwidth(g_w/dpi)
            self.graph.set_figheight(g_h/dpi)
        if self.my_x_data:
            sp = self.graph.add_subplot(111)
            sp.set_ylabel('Price', color="red")
            sp.set_title(self.my_item_data)
            sp.plot(self.my_x_data, self.my_y1_data['min'], color=[1, 0, 0])
            sp.plot(self.my_x_data, self.my_y1_data['avg'], color=[1, 0.5, 0.5])
            sp.plot(self.my_x_data, self.my_y1_data['max'], color=[1, 0.75, 0.75])
            sp2 = sp.twinx()
            sp2.bar(self.my_x_data, self.my_y2_data, color=[0, 0, 1, 0.3])
            sp2.set_ylabel('Volume', color="blue")
            sp.set_xlim(min(self.my_x_data), max(self.my_x_data))
            for l in sp.get_xticklabels():
                l.set_rotation(25)
                l.set_horizontalalignment('right')
        if self.canvas is None:
            self.canvas = FigureCanvasTkAgg(self.graph, master=self)
        self.canvas.draw()
        self.canvas.get_tk_widget().config(width=g_w, height=g_h)
        self.canvas.get_tk_widget().place(x=10, y=self.graph_start_y)

    def do_resize(self, w, h):
        oc_w = w - self.other_items.winfo_x() - 20
        self.other_items.place(width=oc_w)
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
        return [{'id':values[0]['id'], 'tl':tl, 'br':br}]
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
def treemap_draw(tm, ax):
    #draw a fake line, fully transparent
    ax.plot([0, 1], [0, 1], color=[1, 1, 1, 0])
    ax.set_axis_off()
    # for consistent colours
    random.seed(a="123")
    for el in tm:
        r = Rectangle((el['tl']['x'], el['tl']['y']), el['br']['x']-el['tl']['x'], el['br']['y']-el['tl']['y'], facecolor=[random.random(), random.random(), random.random()])
        ax.add_patch(r)
        rx, ry = r.get_xy()
        cx = rx + r.get_width()/2.0
        cy = ry + r.get_height()/2.0
        ax.annotate(el['id'], (cx, cy), ha='center', va='center')

class TreeMapWin(Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.graph = None
        self.canvas = None
        self.tags=[]
        self.reset_data()
        self.create_widgets()

    def reset_data(self):
        # this should be in the form of [{'id':'val1', 'value':1.0}, {'id':'val2', 'value':0.5}, {'id':'val3', 'value':0.4}]
        self.my_tm_data = []

    def search_changed(self, *args):
        v = self.search_val.get()
        if len(v) <= 0:
            self.other_items_val.set("")
            self.reset_data()
            self.update_graph()
            return None
        items = [x for x in v.split(',') if len(x) > 0]
        ev = do_summary(min_volume=10, min_price=0, search_nm=items)
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
            self.my_tm_data.append({'id':e[0], 'value':(e[1] if self.vol_w_check.get() == 0 else e[1]*math.sqrt(e[3]))})
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
        else:
            self.graph.clear()
            self.graph.set_figwidth(g_w/dpi)
            self.graph.set_figheight(g_h/dpi)
        if self.my_tm_data:
            ax = self.graph.add_subplot(111)
            treemap_draw(treemap_plot(self.my_tm_data), ax)
        if self.canvas is None:
            self.canvas = FigureCanvasTkAgg(self.graph, master=self)
        self.canvas.draw()
        self.canvas.get_tk_widget().config(width=g_w, height=g_h)
        self.canvas.get_tk_widget().place(x=10, y=self.graph_start_y)

    def do_resize(self, w, h):
        oc_w = w - self.other_items.winfo_x() - self.vol_w_cb.winfo_width() - 20
        self.other_items.place(width=oc_w)
        # volume w. checkbox on the right hand side
        vw_x = w - 10 - self.vol_w_cb.winfo_width()
        self.vol_w_cb.place(x=vw_x)
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
        self.vol_w_check = IntVar()
        self.vol_w_cb = Checkbutton(self, text="Volume w.", var=self.vol_w_check, command=self.search_changed)
        self.vol_w_cb.place(y=y_plc, height=24)
        y_plc += 24+10
        self.graph_start_y = y_plc

class MainWin(Notebook):
    def __init__(self, master=None):
        super().__init__(master)
        self.master.title("WF Market Hist")
        self.master.myId = 1
        self.master.bind("<Configure>", self.on_resize)
        self.my_w = 0
        self.my_h = 0
        self.hist_frame = None
        self.treemap_frame = None
        self.create_widgets()
        self.pack()

    def on_resize(self, event):
        is_main_window = hasattr(event.widget, 'myId') and (event.widget.myId == 1)
        main_changed_size = is_main_window and ((event.width != self.my_w) or (event.height != self.my_h))
        if is_main_window:
            if main_changed_size:
                if self.hist_frame:
                    self.hist_frame.do_resize(event.width, event.height)
                if self.treemap_frame:
                    self.treemap_frame.do_resize(event.width, event.height)
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
        opts, args = getopt.getopt(sys.argv[1:], "gueshx", ["show-tags", "tags=", "force-tags", "update-detail", "update-all", "graphs", "update", "extract", "summary", "summary-days=", "summary-any", "search", "help", "values="])
    except getopt.GetoptError as err:
        print(err)
        sys.exit(-1)
    exec_mode = 'u'
    extract_values = ['volume', 'min', 'max', 'open', 'close', 'avg', 'w_avg', 'median', 'm_avg']
    s_n_days = 10
    s_min_volume = 24
    s_min_price = 25
    update_all = False
    update_detail = False
    force_tags = False
    tags = []
    for o, a in opts:
        if o in ("-g", "--graphs"):
            exec_mode = 'g'
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

-x, --summary   Quickly print a summary of averaged volumes, min/max prices on the
                last 10 days from today, ordered by min price descending (no other
                input paramater needed, would be ignored)
                By default only items whose average volume >= 24 and average
                min price >= 25 will be reported

--summary-days  Specifies how many days of interval have to be chosen when
                printing out the summary (default 10)
                Specifying any value using this option implies option '-x'

--summary-any   Specifies a flag to report all the items from -x/--summary, thus
                removing the constraints regarding min daily volume and average min
                price (24 and 25 respectively)
                Specifying any value using this option implies option '-x'

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
        elif o in ("-x", "--summary"):
            exec_mode = 'm'
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
    # args should contain the list of items to extract/update
    if exec_mode == 'g':
        display_graphs()
    elif exec_mode == 'u':
        items = get_items_list(args, get_all=update_all)
        print("\tAdding/Updating:")
        for i in items.keys():
            print(i)
        rv = store_hist_data(items, force_tags)
        if update_detail:
            print("\tEntries added:")
            for i in rv:
                if rv[i] > 0:
                    print(i, rv[i])
        print("\tSummary count added:")
        dist = {}
        for k, v in rv.items():
            if v not in dist:
                dist[v] = 0
            dist[v] = dist[v] + 1
        for i in dist:
            print(dist[i], "->", i)
    elif exec_mode == 'e':
        ev = do_extract(args, extract_values, tags)
        do_extract_printout(ev, extract_values)
    elif exec_mode == 's':
        l_items = get_items_list(args)
        print("\tSearch:")
        for i in l_items.keys():
            print(i)
    elif exec_mode == 'm':
        rv = do_summary(n_days=s_n_days, min_volume=s_min_volume, min_price=s_min_price, search_tags=tags)
        print("name,avg min price,avg max price,avg volume")
        for v in rv:
            print(v[0], v[1], v[2], v[3], sep=',')
    elif exec_mode == 't':
        ev = do_extract_tags()
        print("\tTags:")
        for t in ev:
            print(t)

if __name__ == "__main__":
    main()
