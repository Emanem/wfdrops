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
from matplotlib.figure import Figure
import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

G_DB_NAME = "wf_mkt_hist.db"
G_DB_ITEMS_NAME = "items"
G_DB_ITEMS_HIST = "hist"
G_WFM_USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.47 Safari/537.36'
G_SLEEP_THROTTLE = 0.5

def db_setup(db):
    cur = db.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS " + G_DB_ITEMS_NAME + " (name text)")
    cur.execute("CREATE TABLE IF NOT EXISTS " + G_DB_ITEMS_HIST + " (id integer, ts timestamp, volume integer, min integer, max integer, open integer, close integer, avg real, w_avg real, median real, m_avg real)")
    cur.execute("CREATE INDEX IF NOT EXISTS i1 ON " + G_DB_ITEMS_HIST + "(id)")
    db.commit()
    return None

def db_fetch_names(db, nm):
    cur = db.cursor()
    for i in nm:
        q = "INSERT INTO " + G_DB_ITEMS_NAME + "(name) SELECT ? WHERE NOT EXISTS (SELECT 1 FROM " + G_DB_ITEMS_NAME + " WHERE name=?)";
        cur.execute(q, (i, i))
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
            rv.append((datetime.datetime.fromisoformat(x['datetime']), int(x['volume']), int(x['min_price']), int(x['max_price']), int(x['open_price']), int(x['closed_price']), float(x['avg_price']), float(x['wa_price']), float(x['median']), float(x.get('moving_avg', 0.0))))
    return rv

def get_wfm_webapi(str_url, https_cp):
    f = https_cp.urlopen('GET', str_url, headers={'User-Agent': G_WFM_USER_AGENT})
    return f.data.decode('utf-8')

def get_hist_stats(item_name, https_cp):
    str_url = '/items/' + item_name.replace('&', 'and').replace('-', '_').replace(' ', '_').replace('\'', '').replace('(', '').replace(')', '').lower() + '/statistics'
    data = get_wfm_webapi(str_url, https_cp)
    return parse_hist_stats(data)

def store_hist_data(item_names):
    print("\tFetching:")
    all_items = {}
    n_digits = len(str(len(item_names)))
    cnt = 0
    # create the HTTPS pool here
    https_cp = urllib3.HTTPSConnectionPool('warframe.market')
    for nm in item_names:
        cnt += 1
        print("[{count:{fill}{align}{width}}/{total}]".format(count=cnt, total=len(item_names), fill=' ', align='>', width=n_digits), end='\t')
        print(nm, end='...')
        tm_start = time.monotonic()
        try:
            all_items[nm] = get_hist_stats(nm, https_cp)
        except Exception as e:
            print("Error, carrying on (", e, ")")
        else:
            # this is not great - but it does work...
            tm_end = time.monotonic()
            print('done', tm_end-tm_start, 's', "(" + str(len(all_items[nm])) + " entries)")
        finally:
            tm_end = time.monotonic()
            sleep_throttle = G_SLEEP_THROTTLE - (tm_end - tm_start)
            if sleep_throttle > 0.0:
                time.sleep(sleep_throttle)
    db = sqlite3.connect(G_DB_NAME)
    db_setup(db)
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
            rv[k['item_name']] = 0
        return rv
    r_items = []
    for s in search_nm:
        r_items.append(re.compile(r'.*' + re.escape(s.strip()) + r'.*', re.IGNORECASE))
    rv = {}
    for k in jdata['payload']['items']:
        for r_i in r_items:
            if r_i.match(k['item_name']) is not None:
                #print("k", k)
                rv[k['item_name']] = 0
    return list(rv.keys())

def do_extract(search_nm, e_values, wildcard_ws=False):
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
ON      (i.rowid=h.id)
WHERE   1=1
AND     (
        1=0
"""
    items_q = ""
    for n in search_nm:
        if wildcard_ws:
            n_v = re.split(r'\s+', n)
            n = '%'.join(n_v)
        items_q += "\tOR i.name LIKE '%" + n + "%'\n"
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

def do_summary(n_days=10, min_volume=24, min_price=25):
    query = """
select x.name, x.a_min, x.a_max, x.a_vol
from (
	select 	i.name, avg(volume) as a_vol, avg(min) as a_min, avg(max) as a_max
	FROM	items i
	JOIN	hist h
	ON		(i.ROWID=h.id)
	WHERE	1=1
	AND		h.ts > DATE('now', ?)
	AND		NOT i.name LIKE '%set'
	GROUP BY	i.name
) x
WHERE	1=1
AND		x.a_vol >= ?
AND		x.a_min >= ?
ORDER BY	x.a_min DESC
"""
    interval_q = "-" + str(n_days) + " days"
    db = sqlite3.connect(G_DB_NAME)
    db_setup(db)
    cur = db.cursor()
    ri = cur.execute(query, (interval_q, min_volume, min_price))
    print("name,avg min price,avg max price,avg volume")
    for v in ri:
        print(v[0], v[1], v[2], v[3], sep=',')
    db.close()

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

class MainWin(Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.master.title("WF Market Hist")
        self.master.myId = 1
        self.master.bind("<Configure>", self.on_resize)
        self.master.bind_all('<KeyPress>', self.on_key_press)
        self.my_w = 0
        self.my_h = 0
        self.graph = None
        self.canvas = None
        self.my_item_data = ""
        self.reset_data()
        self.create_widgets()

    def reset_data(self):
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
        self.other_items_val.set(', '.join(sorted_items))
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
        g_h = (h-self.graph_start_y-10)
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
            self.canvas = FigureCanvasTkAgg(self.graph, master=self.master)
        self.canvas.draw()
        self.canvas.get_tk_widget().config(width=g_w, height=g_h)
        self.canvas.get_tk_widget().place(x=10, y=self.graph_start_y)

    def on_resize(self, event):
        is_main_window = hasattr(event.widget, 'myId') and (event.widget.myId == 1)
        main_changed_size = is_main_window and ((event.width != self.my_w) or (event.height != self.my_h))
        if is_main_window:
            if main_changed_size:
                # update the width of other choices label
                oc_w = event.width - self.other_items.winfo_x() - self.quit.winfo_width() - 20
                self.other_items.place(width=oc_w)
                # update quit button place
                q_pos_x = self.master.winfo_width() - 10 - self.quit.winfo_width()
                self.quit.place(x=q_pos_x)
                # update graph
                self.update_graph()
            self.my_w = event.width
            self.my_h = event.height

    def on_key_press(self, event):
        if event.keysym == 'Escape':
            self.master.destroy()

    def create_widgets(self):
        y_plc = 10
        # Label - "Search for item:"
        self.label_top = Label(self.master, text="Search for item:", anchor=W)
        self.label_top.place(x=10, y=y_plc, width=128, height=24)
        # Entry to execute the search
        self.search_val = StringVar()
        self.search_val.trace_add("write", self.search_changed)
        self.search_entry = Entry(self.master, textvariable=self.search_val)
        self.search_entry.place(x=138, y=y_plc, width=128, height=24)
        # Label to display the other choices
        # don't care about width, we sort it out in 'on_resize'
        self.other_items_val = StringVar()
        self.other_items = Label(self.master, textvariable=self.other_items_val, anchor=W)
        self.other_items.place(x=138+128+10, y=y_plc, height=24)
        # Button - "Quit" don't care about x location
        # we sort it out automatically in 'on_resize'
        self.quit = Button(self.master, text="Quit", command=self.master.destroy)
        self.quit.place(x=0, y=y_plc, height=24)
        y_plc += 24+10
        self.graph_start_y = y_plc
        self.update_graph(640, 480)

def display_graphs():
    root = Tk()
    root.minsize(640, 480)
    root.geometry("640x480")
    app = MainWin(master=root)
    app.mainloop()
    return None

def main():
    try:
        opts, args = getopt.getopt(sys.argv[1:], "gueshx", ["update-all", "graphs", "update", "extract", "summary", "summary-days=", "summary-any", "search", "help", "values="])
    except getopt.GetoptError as err:
        print(err)
        sys.exit(-1)
    exec_mode = 'u'
    extract_values = ['volume', 'min', 'max', 'open', 'close', 'avg', 'w_avg', 'median', 'm_avg']
    s_n_days = 10
    s_min_volume = 24
    s_min_price = 25
    update_all = False
    for o, a in opts:
        if o in ("-g", "--graphs"):
            exec_mode = 'g'
        elif o in ("-u", "--update"):
            exec_mode = 'u'
        elif o in ("--update-all"):
            exec_mode = 'u'
            update_all = True
        elif o in ("-e", "--extract"):
            exec_mode = 'e'
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
        l_items = get_items_list(args, get_all=update_all)
        print("\tAdding/Updating:")
        for i in l_items:
            print(i)
        rv = store_hist_data(l_items)
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
        ev = do_extract(args, extract_values)
        do_extract_printout(ev, extract_values)
    elif exec_mode == 's':
        l_items = get_items_list(args)
        print("\tSearch:")
        for i in l_items:
            print(i)
    elif exec_mode == 'm':
        do_summary(n_days=s_n_days, min_volume=s_min_volume, min_price=s_min_price)

if __name__ == "__main__":
    main()
