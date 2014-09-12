import os
import argparse
import csv
import sys
import re

# set up command-line arguments
FLAGS = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
A = FLAGS.add_argument
A('-c', '--columnName', type = str, help = 'Column Name, such as \'Quiz 1 (3294843)\'')
A('-m', '--maxV', type = int, help = 'Maxmun score allowed, such as \'10\' for Quiz')
A('-i', '--info', metavar = 'FILE', help = 'CSV file containing student information')
A('-o', '--output', metavar = 'FILE', help = 'name of the outputed .CSV file')

def main(args):
    f = open(args.info)
    
    # column index ...
    index = {}
    index['name'] = 0   # column index for 'Name', change it base on the CSV file
    index['cid'] = 1
    index['eid'] = 2
    index['score'] = 8   # updated based on 'columnName' 
 
    names = {}
    eids = {}
    scores = {}
    noScore = 0
    total = 0
    try: 
        reader = csv.reader(f)
        data = reader.next()
        for i in xrange(0, len(data)):
            if args.columnName in data[i]:
                index['score'] = i
                print '>> Taget column: ', data[i]

        reader.next() ## skip the second line
        for line in reader:
            names[line[index['cid']]] = line[index['name']]   # cid -> name 
            eids[line[index['eid']]] = line[index['cid']]     # eid -> cid
            total += 1
            if len(line[index['score']]) == 0:
                noScore += 1
            else :
                scores[line[index['cid']]] = line[index['score']]	
    finally: 
        f.close()
    print ">> Total:", total, ", where", noScore, "has no score yet."  

    while (True) :
    	uteid = raw_input(">> input student ut eid (\'done\' to stop): ")
        if (uteid.lower() == "done") :
            print '>> Thanks for using! Scores saved to \"', args.output, '\"\n'
            break
        if uteid in eids :
            updateScore(uteid, eids, names, scores, index, args)
        else:
            similarID = vagueSearch(eids, uteid)
            if len(similarID) == 0 :
                print ">> Student ", uteid, "is not found, give up"
            elif len(similarID) == 1:
                confirm = raw_input(">> No student found for " + uteid + ", do you mean " + similarID[0] + " ('N' for No): ")
                if len(confirm) == 0 or (confirm[0] != 'n' and confirm[0] != 'N'): 
                    updateScore(similarID[0], eids, names, scores, index, args)
            else :
                print ">> Do you mean the following student(s): "
                for i in xrange(0, len(similarID)):
                    item = similarID[i] 
                    print ">> [", i + 1, "]  EID: ", item, " Name: ", names[eids[item]]
                choice = get_Int(">> Make a choice, 0 to skip: ", 0, len(similarID))
                if choice > 0:
                    updateScore(similarID[choice - 1], eids, names, scores, index, args)
        print ''

def updateScore(uteid, eids, names, scores, index, args):
    cvid = eids[uteid]
    score = get_Int(">> input score for " + names[cvid] + '(' + uteid + "): ", 0, args.maxV)
    if cvid not in scores :
        scores[cvid] = score
        print ">> Sucessfully logged socre for ", names[cvid] , '(', uteid, ') @ ' + str(score) 
    else :
        print ">> Score already exists for", names[cvid] , '(', uteid, ') @ ' + str(scores[cvid]), ' updated to ', str(score)
        scores[cvid] = score
    write(scores, index, args)   # update output on each modification of score



# in case of typo... 3 can be changed to other edit distance
def vagueSearch(eids, uteid):
    similarID = []
    for eid in eids :
        if minDistance(uteid, eid) < 3 :
            similarID.append(eid)
    return similarID

# get edit distance for two strings (ut eid here)
def minDistance(word1, word2):
    len1 = len(word1)
    len2 = len(word2)
    # initialization
    dp = [ [0 for j in xrange(len2 + 1)] for i in xrange(len1 + 1) ]
    for i in xrange(len1 + 1):
        dp[i][0] = i
    for j in xrange(len2 + 1):
        dp[0][j] = j
    for i in xrange(1, len1 + 1):
        for j in xrange(1, len2 + 1):
            dp[i][j] = dp[i-1][j-1] if word1[i-1] == word2[j-1] else min(dp[i-1][j], dp[i][j-1], dp[i-1][j-1]) + 1
    return dp[len1][len2]


# write to file
def write(scores, index, args):    
    f = open(args.info)
    reader = csv.reader(f)
    outFile = open(args.output, 'wb')
    writer = csv.writer(outFile, delimiter = ',', quotechar = '"', quoting = csv.QUOTE_MINIMAL)
    writer.writerow(reader.next())
    writer.writerow(reader.next())
    writer.writerow(reader.next())

    for studentData in reader:
        id = studentData[index['cid']]
        if len(id) == 0: 
            continue
        elif id in scores:
            studentData[index['score']] = str(scores[id])
        writer.writerow(studentData)

    f.close()
    outFile.close()


# get Input from terminal within range [minV, maxV]
def get_Int(prop, minV, maxV):
    while True:
        try:
            intTarget = int(raw_input(prop))
        except ValueError:
            print 'Integer expected'
            continue
        else:
            if intTarget < minV or intTarget > maxV:
                print 'range %d - %d' % (minV, maxV)
                continue
            else:
                return (intTarget)    

if __name__ == '__main__':
    main(FLAGS.parse_args())
 
