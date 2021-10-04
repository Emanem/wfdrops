#!/usr/bin/env python3

import math
import random

def coumpound_all_prob(prob_list):
    total_prob = 0.0
    l = len(prob_list)
    if(l==1):
        return prob_list[0]
    elif(l==2):
        return 2.0*prob_list[0]*prob_list[1]
    # else recursive step
    for i, el in enumerate(prob_list):
        # create sublist
        sl = prob_list[:]
        sl.pop(i)
        total_prob += el * coumpound_all_prob(sl)
    return total_prob

def coumpound_all_prob_fact(prob_list, tries):
    if(tries < len(prob_list)):
        return None
    total_prob = 1.0
    for i in prob_list:
        total_prob *= i
    base_prob = total_prob * math.factorial(len(prob_list))
    accum_mult = 1.0
    rem_prob = 1.0 - sum(prob_list)
    print(rem_prob)
    for i in range(tries - len(prob_list)):
        for j in prob_list:
            accum_mult += j
        accum_mult += rem_prob
    print(accum_mult)
    return accum_mult * base_prob

def single_run_mc(prob_list, tries):
    # build a simple list with cumulated values
    accum = 0.0
    a_pl = []
    res_pl = []
    for i in prob_list:
        accum += i
        a_pl.append(accum)
        res_pl.append(0)
    #print(a_pl)
    for i in range(tries):
        cr = random.randint(1, 1000000)/1000000.0
        #print(cr)
        for j in range(len(a_pl)):
            if cr <= a_pl[j]:
                res_pl[j] = 1
                break
    #print(res_pl)
    accum = 0
    for i in res_pl:
        accum += i
    #print(accum >= len(res_pl), "\n")
    return accum >= len(res_pl)

def coumpound_all_prob_mc(prob_list, tries):
    if(tries < len(prob_list)):
        return None
    total_ok = 0
    samples = 10000000
    i = 0
    while i < samples:
        total_ok += 1 if single_run_mc(prob_list, tries) else 0
        i += 1
    return 1.0 * total_ok / samples

def main():
    mv = [0.3872, 0.3872, 0.2256]
    #mv = [0.1, 0.1, 0.1]
    n_tries = 4
    print(coumpound_all_prob_fact(mv, n_tries))
    print(coumpound_all_prob_mc(mv, n_tries))

if __name__ == "__main__":
    main()

