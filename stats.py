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
    total_prob = 1.0
    for i in prob_list:
        total_prob *= i
    return total_prob * math.factorial(len(prob_list))

def coumpound_all_prob_mc(prob_list, tries):
    total_ok = 0
    samples = 100000
    i = 0
    while i < samples:
        # evaluate prob list
        good = True
        for j in prob_list:
            cr = random.randint(0, 10000)/10000.0
            if cr > j:
                good = False
                break
        if good:
            total_ok += 1
        i += 1
    return 1.0 * total_ok / samples * 6

def main():
    mv = [0.3872, 0.3872, 0.2256]
    #mv = [0.25, 0.25, 0.5]
    print(coumpound_all_prob(mv))
    print(coumpound_all_prob_fact(mv, len(mv)))
    print(coumpound_all_prob_mc(mv, len(mv)))

if __name__ == "__main__":
    main()

