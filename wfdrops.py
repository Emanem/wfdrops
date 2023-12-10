#!/usr/bin/env python3

from html.parser import HTMLParser
from tkinter import *
from tkinter import font
from tkinter import messagebox
import re
import math
import copy
import urllib.request
import os.path

# regex to match for mission titles and more
mission_r = re.compile(r'([:a-z ]+)/([a-z ]+) \(([a-z ]+)\)', re.IGNORECASE)
rotation_r = re.compile(r'rotation ([ABC])', re.IGNORECASE)
chance_r = re.compile(r'[a-z]+ \((\d+).(\d+)\%\)', re.IGNORECASE)
drops_url_r = re.compile(r'^http(s|)\://.*$', re.IGNORECASE)
mods_drop_r = re.compile(r'mod drop chance\: (\d+).(\d+)\%', re.IGNORECASE)

# local file name holding drops
drops_html_file = "wfdrops.html"

# main map of <item> --> <type> --> <planet> --> <location> --> <rotation> --> <chance>
items_map = {}

# secondary maps of <mod> --> <source (enemy)> --> <chance>
mods_map = {}

class MissionParser(HTMLParser):
    def __init__(self):
        self.in_tr = False
        self.in_th = False
        self.in_td = False
        self.table_name = ''
        self.planet = ''
        self.location = ''
        self.m_type = ''
        self.rotation = 'none'
        self.cur_item = ''
        self.mod_source = ''
        self.mod_source_chance = 0.0
        self.mod_name = ''
        super().__init__()

    def handle_starttag(self, tag, attrs):
        #print("Encountered a start tag:", tag, end=' ')
        #for a in attrs:
        #    print(a[0], a[1], end=' ')
        #print('')
        if tag == 'tr':
            self.in_tr = True
            # if we have blank row, reset the current mission, ...
            if ("class", "blank-row") in attrs:
                self.planet = ''
                self.location = ''
                self.m_type = ''
                self.rotation = 'none'
                self.cur_item = ''
                self.mod_source = ''
                self.mod_source_chance = 0.0
                self.mod_name = ''
        if tag == 'th':
            self.in_th = True
        if tag == 'td':
            self.in_td = True
        if tag == 'h3':
            if ("id", "missionRewards") in attrs:
                self.table_name = 'missions'
            elif ("id", "modByAvatar") in attrs:
                self.table_name = 'mba'
            else:
                self.table_name = ''

    def handle_endtag(self, tag):
        #print("Encountered an end tag :", tag)
        if tag == 'tr':
            self.in_tr = False
        if tag == 'th':
            self.in_th = False
        if tag == 'td':
            self.in_td = False

    def handle_data_missions(self, data):
        if(self.in_tr and self.in_th):
            #print("Encountered some data  :", data)
            allm = mission_r.search(data)
            rotm = rotation_r.search(data)
            if allm is not None:
                # also reset rotation... some missions
                # don't have the same
                self.set_cur_mission(allm)
                self.rotation = 'none'
            elif rotm is not None:
                self.rotation = rotm.group(1)
        elif (self.in_tr and self.in_td and len(self.planet)>0):
            # Process rows of data, first column
            if len(self.cur_item) == 0:
                self.cur_item = data
            else:
                #extract the percentage
                chancem = chance_r.search(data)
                if chancem is not None:
                    chancef = float(chancem.group(1)) + float(chancem.group(2))/100.0
                    # init the multi level map
                    if items_map.get(self.cur_item, None) is None:
                        items_map[self.cur_item] = {}
                    if items_map[self.cur_item].get(self.m_type, None) is None:
                        items_map[self.cur_item][self.m_type] = {}
                    if items_map[self.cur_item][self.m_type].get(self.planet, None) is None:
                        items_map[self.cur_item][self.m_type][self.planet] = {}
                    if items_map[self.cur_item][self.m_type][self.planet].get(self.location, None) is None:
                        items_map[self.cur_item][self.m_type][self.planet][self.location] = {}
                    if items_map[self.cur_item][self.m_type][self.planet][self.location].get(self.rotation, None) is None:
                        items_map[self.cur_item][self.m_type][self.planet][self.location][self.rotation] = {}
                    items_map[self.cur_item][self.m_type][self.planet][self.location][self.rotation] = chancef
                # reset the item name
                self.cur_item = ''

    def handle_data_mods(self, data):
        if(self.in_tr and self.in_th):
            if(len(self.mod_source) == 0):
                self.mod_source = data
            else:
                mdc = mods_drop_r.search(data)
                if (mdc is not None):
                    self.mod_source_chance = float(mdc.group(1)) + float(mdc.group(2))/100.0
        elif (self.in_tr and self.in_td and len(self.mod_source)>0 and len(data) > 0):
            if(len(self.mod_name) == 0):
                self.mod_name = data
            else:
                # get the chance of given mod
                chancem = chance_r.search(data)
                if (chancem is not None):
                    chancef = float(chancem.group(1)) + float(chancem.group(2))/100.0
                    # add to multi level map
                    if mods_map.get(self.mod_name, None) is None:
                        mods_map[self.mod_name] = {}
                    mods_map[self.mod_name][self.mod_source] = self.mod_source_chance/100.0 * chancef
                self.mod_name = ''

    def handle_data(self, data):
        if self.table_name == 'missions':
            self.handle_data_missions(data)
        elif self.table_name == 'mba':
            self.handle_data_mods(data)
    
    def set_cur_mission(self, match):
        self.planet = match.group(1)
        self.location = match.group(2)
        self.m_type = match.group(3)

# setup with mission types and rewards
m_rewards = {
    'Survival' : { 'rot' : ['A', 'A', 'B', 'C'], 'tm_min' : 5 },
    'Defense' : { 'rot' : ['A', 'A', 'B', 'C'], 'tm_min' : 5 },
    'Interception' : { 'rot' : ['A', 'A', 'B', 'C'], 'tm_min' : 4 },
    'Spy' : { 'rot' : ['A', 'B', 'C'], 'tm_min' :  4 },
    'Excavation' : { 'rot' : ['A', 'A', 'B', 'C'], 'tm_min' : 3 },
    'Exterminate' : { 'rot' : ['none'], 'tm_min' : 4 },
    'Capture' : { 'rot' : ['none'], 'tm_min' : 3 },
    'Rush' : { 'rot' : ['C'], 'tm_min' : 3 },
    'Defection' : { 'rot' : ['A', 'A', 'B', 'C'], 'tm_min' : 5 },
    'Rescue' : { 'rot' : ['C'], 'tm_min' : 4 },
    'Caches' : { 'rot' : ['A', 'B', 'C'], 'tm_min' : 5 },
    'Disruption' : { 'rot' : ['B', 'B', 'C', 'C'], 'tm_min' : 5 },
    'Sabotage' : { 'rot' : ['none'], 'tm_min' : 4 },
    'Conclave' : { 'rot' : ['A', 'B'], 'tm_min' : 10 },
    'Mobile Defense' : { 'rot' : ['none'], 'tm_min' : 5 },
    'Assassination' : { 'rot' : ['none'], 'tm_min' : 10 },
    'Infested Salvage' : { 'rot' : ['A', 'A', 'B', 'C'], 'tm_min' : 5 }
        }

def type_get_odds(m_type, m_planet, m_loc, rot_map):
    # the odds of having one or more
    # are the odds one minus not having any
    # in all runs 
    if m_rewards.get(m_type, None) is None:
        print("Can't find type:", m_type) 
        return None
    odds_not = 1.0
    iter_r = 0
    max_iter_r = 0
    for rot in m_rewards[m_type]['rot']:
        iter_r += 1
        if rot_map.get(rot, None) is not None:
            odds_not = odds_not * (1.0 - rot_map[rot]/100.0)
            max_iter_r = iter_r
    total_time = max_iter_r*m_rewards[m_type]['tm_min']
    if(total_time <= 0):
        return None
    hour_time = 60 / total_time
    odds_per_hour = 1.0 - math.pow(odds_not, hour_time)
    #print(m_type, m_planet, m_loc, odds_per_hour, total_time, rot_map)
    return (m_type, m_planet + '/' + m_loc, odds_per_hour, total_time, max_iter_r)

def lookup_all_odds(name):
    # pick name, split by whitespaces, strip
    # escape and surround by regex...
    sv = name.split()
    if len(sv) <= 0:
        return {}
    reg_s = ".*"
    for i in sv:
        reg_s += re.escape(i) + ".*"
    nm = re.compile(reg_s, re.IGNORECASE)
    rv = {}
    for i in items_map.keys():
        is_m = nm.match(i)
        if is_m is not None:
            rv[i] = []
            m_type = items_map[i]
            all_odds = []
            for t in m_type.keys():
                for p in m_type[t].keys():
                    for l in m_type[t][p].keys():
                        odds = type_get_odds(t, p, l, m_type[t][p][l])
                        if odds is not None:
                            all_odds.append(odds)
            sorted_odds = sorted(all_odds, key=lambda x: x[2], reverse=True)
            rv[i] = sorted_odds
    return rv

def combine_multi_odds(s):
    keys = []
    # for each element in s, identify their first key
    for el in s:
        if len(el) <= 0:
            keys.append(None)
        else:
            keys.append(list(el.keys())[0])
    # make keys unique
    for i, v in enumerate(keys):
        if v is None:
            continue
        found = False
        j = i+1
        while j < len(keys):
            if keys[j] == v:
                keys[j] = None
            j += 1
    print("Keys:", keys)
    # now that we got the keys we need to recombine values...
    # when applicable
    rv = []
    idx = 0
    label = ""
    for k in keys:
        if k is None:
            idx += 1
            continue
        if len(label) <= 0:
            label = k
        else:
            label = label + ", " + k
        cur_values = copy.deepcopy(s[idx][k])
        # make the odds reverse
        for i, v in enumerate(cur_values):
            cur_values[i] = (v[0], v[1], 1.0 - v[2], v[3], v[4])
        if len(rv) <= 0:
            rv = cur_values
        else:
            # this is where we have to merge...
            # a bit complex
            # scroll through rv values and find out if those exist
            # in the new cur_values
            # add cur values to a set
            cv = {}
            cur_idx = 0
            for i in cur_values:
                cv[i[1]] = cur_idx
                cur_idx += 1
            #iterate reverse
            for i in range(len(rv)-1, -1, -1):
                if rv[i][1] not in cv:
                    rv.pop(i)
                else:
                    # amend the reverse probability
                    # and set max time
                    cv_var = cur_values[cv[rv[i][1]]]
                    cv_max_tm = max(rv[i][3], cv_var[3])
                    cv_max_iter = max(rv[i][4], cv_var[4])
                    # given the mission is the same, we now need to
                    # normalize if the numbers of tries are different
                    # because the hourly chance% needs to be rescaled
                    if rv[i][4] == cv_var[4]:
                        cv_prop = rv[i][2] * cv_var[2]
                    elif rv[i][4] > cv_var[4]:
                        # we need to rescale cv_var[2]
                        cv_prop = rv[i][2] * math.pow(cv_var[2], 1.0/(60/cv_var[3])*(60/rv[i][3]))
                    else:
                        # need to rescale rv[i][4]
                        cv_prop = math.pow(rv[i][2], 1.0/(60/rv[i][3])*(60/cv_var[3])) * cv_var[2]
                    rv[i] = (rv[i][0], rv[i][1], cv_prop, cv_max_tm, cv_max_iter)
        idx += 1
    # we need to reverse probabilities once more
    for i, v in enumerate(rv):
        rv[i] = (v[0], v[1], 1.0 - v[2], v[3], v[4])
    return label, sorted(rv, key=lambda x: x[2], reverse=True) 

max_reward_rows = 10

def parse_local_data():
    if not os.path.isfile(drops_html_file):
        messagebox.showwarning(title="Warning", message="Local drop file is missing, please update drops")
        return None
    htmldata = open(drops_html_file, 'r').read()
    # parse it
    p = MissionParser()
    p.feed(htmldata)

def update_do_closew(d_file, w):
    if not drops_url_r.match(d_file):
        messagebox.showerror(master=w, title="Error", message="Please spcify a valid URL for a drops html file\n(i.e. 'https://www.warframe.com/droptables')")
        return None
    urllib.request.urlretrieve(d_file, drops_html_file)
    parse_local_data()
    w.destroy()

def times_do_closew(d_missions, w, sv):
    for k in d_missions:
        m_rewards[k]["tm_min"] = int(d_missions[k].get())
    # this is to trigger a refresh
    cur_se = sv.get()
    sv.set(cur_se)
    w.destroy()

def update_popup():
    win = Toplevel()
    win.wm_title("Update Drops")
    win.geometry(str(2*10 + 90 + 256) + "x" + str(2*10+24*2))
    l = Label(win, text="Drops URL", anchor=W)
    l.place(x=10, y=10, width=90, height=24)
    d = StringVar()
    d.set('https://www.warframe.com/droptables')
    de = Entry(win, textvariable=d)
    de.place(x=10+90, y=10, width=256, height=24)
    b = Button(win, text="Update", command=lambda: update_do_closew(d.get(), win))
    b.place(x=10, y=10+24, height=24)

def times_popup(sv):
    y_plc = 10
    win = Toplevel()
    win.wm_title("Update Times")
    n_missions = len(m_rewards.keys())
    win.geometry(str(2*10 + 291) + "x" + str(2*10+24*2 + 24*n_missions))
    l = Label(win, text="Mission/Rotation average times", anchor=W)
    l["font"] = font.Font(weight="bold")
    l.place(x=10, y=y_plc, height=24)
    y_plc += 24
    # main elements
    d_missions = {}
    for k in m_rewards:
        l = Label(win, text=k, anchor=W)
        l.place(x=10, y=y_plc, height=24, width=128)
        d_missions[k] = StringVar()
        d_missions[k].set(m_rewards[k]["tm_min"])
        de = Entry(win, textvariable=d_missions[k], justify=RIGHT)
        de.place(x=10+128, y=y_plc, width=48, height=24)
        y_plc += 24
    b = Button(win, text="Apply/Close", command=lambda: times_do_closew(d_missions, win, sv))
    b.place(x=10, y=y_plc, height=24)
                    
class MainWin(Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.master.title("WFDrops")
        self.create_widgets()
        parse_local_data()

    def reset_rewards(self):
        self.label_reward["text"] = "(none)"
        for i in range(0, max_reward_rows):
            self.res[i][0]["text"] = ""
            self.res[i][1]["text"] = ""
            self.res[i][2]["text"] = ""
            self.res[i][3]["text"] = ""
            self.res[i][4]["text"] = ""

    def display_rewards(self, rewards):
        for i in range(len(rewards)):
            if(i >= max_reward_rows):
                break
            self.res[i][0]["text"] = rewards[i][0]
            self.res[i][1]["text"] = rewards[i][1]
            self.res[i][2]["text"] = "{:5.2f}".format(100.0*rewards[i][2]) + "%"
            self.res[i][3]["text"] = str(rewards[i][3]) + " mins."
            self.res[i][4]["text"] = rewards[i][4]
        i = len(rewards)
        while i < max_reward_rows:
            self.res[i][0]["text"] = ""
            self.res[i][1]["text"] = ""
            self.res[i][2]["text"] = ""
            self.res[i][3]["text"] = ""
            self.res[i][4]["text"] = ""
            i += 1

    def search_changed(self, *args):
        self.reset_rewards()
        v = self.search_val.get()
        if len(v) <= 0:
            return None
        searches = v.split(",")
        if len(searches) <= 0:
            return None
        for i in range(len(searches)-1, -1, -1):
            if len(searches[i]) <= 0:
                searches.pop(i)
        multi_odds = []
        for i in searches:
            multi_odds.append(lookup_all_odds(i.strip()))
        print("\n", multi_odds)
        label, values = combine_multi_odds(multi_odds)
        self.label_reward["text"] = label
        if len(values) == 0:
            return None
        self.display_rewards(values)

    def create_widgets(self):
        y_plc = 10
        self.label_top = Label(self.master, text="Search for reward:", anchor=W)
        self.label_top.place(x=10, y=y_plc, width=128, height=24)
        self.search_val = StringVar()
        self.search_val.trace_add("write", self.search_changed)
        self.search_entry = Entry(self.master, textvariable=self.search_val)
        self.search_entry.place(x=138, y=y_plc, width=128, height=24)
        self.update_btn = Button(self.master, text="Update Drops", command=update_popup)
        self.update_btn.place(x=138+128+10, y=y_plc, height=24)
        self.times_btn = Button(self.master, text="Update Times", command=lambda: times_popup(self.search_val))
        self.times_btn.place(x=138+128+10+128, y=y_plc, height=24)
        # 
        y_plc += 24
        self.label_reward = Label(self.master, text="", anchor=W)
        self.label_reward["font"] = font.Font(weight="bold")
        self.label_reward.place(x=10, y=y_plc, width=384, height=24)
        # set the titles
        y_plc += 24
        x_plc = 10
        cur_l_row = []
        cur_l_row.append(Label(self.master, text="Mission Type", fg="blue", anchor=W))
        cur_l_row[-1].place(x=x_plc, y=y_plc, width=96, height=24)
        x_plc += 96
        cur_l_row.append(Label(self.master, text="Location", fg="blue", anchor=W))
        cur_l_row[-1].place(x=x_plc, y=y_plc, width=192, height=24)
        x_plc += 192
        cur_l_row.append(Label(self.master, text="Drop %", fg="blue", anchor=W))
        cur_l_row[-1].place(x=x_plc, y=y_plc, width=64, height=24)
        x_plc += 64
        cur_l_row.append(Label(self.master, text="Run Time", fg="blue", anchor=E))
        cur_l_row[-1].place(x=x_plc, y=y_plc, width=64, height=24)
        x_plc += 64
        cur_l_row.append(Label(self.master, text="Iter.", fg="blue", anchor=E))
        cur_l_row[-1].place(x=x_plc, y=y_plc, width=48, height=24)
        # init top 5 label rows
        self.res = []
        for i in range(0, max_reward_rows):
            y_plc += 24
            x_plc = 10
            cur_l_row = []
            cur_l_row.append(Label(self.master, text="AAAAA"+str(i), anchor=W))
            cur_l_row[-1].place(x=x_plc, y=y_plc, width=96, height=24)
            x_plc += 96
            cur_l_row.append(Label(self.master, text="BBBBB"+str(i), anchor=W))
            cur_l_row[-1].place(x=x_plc, y=y_plc, width=192, height=24)
            x_plc += 192
            cur_l_row.append(Label(self.master, text="CCCCC"+str(i), anchor=W))
            cur_l_row[-1].place(x=x_plc, y=y_plc, width=64, height=24)
            x_plc += 64
            cur_l_row.append(Label(self.master, text="DDDDD"+str(i), anchor=E))
            cur_l_row[-1].place(x=x_plc, y=y_plc, width=64, height=24)
            x_plc += 64
            cur_l_row.append(Label(self.master, text="EEEEE"+str(i), anchor=E))
            cur_l_row[-1].place(x=x_plc, y=y_plc, width=48, height=24)
            self.res.append(cur_l_row)
        #
        y_plc += 24
        self.quit = Button(self.master, text="Exit", command=self.master.destroy)
        self.quit.place(x=10, y=y_plc, height=24)
        self.reset_rewards()

def main():
    root = Tk()
    root.geometry("540x" + str(24*max_reward_rows + 92 + 24))
    app = MainWin(master=root)
    app.mainloop()

if __name__ == "__main__":
    main()
