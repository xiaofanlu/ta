import argparse
import contextlib
import csv
import difflib
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import multiprocessing
try:
    from Queue import Queue, Empty
except ImportError:
    from queue import Queue, Empty
from subprocess import PIPE, Popen
from threading  import Thread
import select
import time
import  fcntl
import errno
import webbrowser
from collections import defaultdict

# set up command-line arguments
FLAGS = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
A = FLAGS.add_argument
A('-a', '--assignment', type=int, help='Assignment Number')
A('-c', '--cslogin', type=str, help='CS login of grader')
A('-f', '--folder', metavar='DIR', help='Folder with all required files')
A('-g', '--grader', type=str, metavar='Grader\'s Name', 
                                                 help='Name of the grader')
A('-i', '--input', default=[], nargs='+', type=str, metavar='FILE', help='Test input base file name')
A('-o', '--output', default=[], nargs='+', type=str, metavar='FILE', help='Test output base file name')
A('-n', '--info', metavar='FILE', help='CSV file containing student information')
A('-r', '--rubric', metavar='FILE', help='txt file cotaining the grading rubric')
A('-s', '--solution', default='Song.java', metavar='FILE', help='instructor solution')
A('-t', '--turnin', default='turnin', metavar='DIR', help='turnin folder with .java file')
A('-w', '--webbrowser', default=False, type=bool, help='Open diff result in webbrowser if True')



# module-local exception classes
class Error(Exception): pass

class CompileError(Error):
    def __init__(self, out, err, filename):
        self.out = out
        self.err = err
        self.filename = filename

class TimeOutError(Error):
    def __init__(self, time):
        self.time = time

# Execute a command, uses blocking        
class Command(object):
    # Input is a string of lines seperated by '/n'
    # Each line is passsed to the program sequentially
    def __init__(self, args, input):
        self.args = args
        self.input = input.splitlines(True)
        self.out = ""
        self.err = ""
    
    def run(self, timeout):
        # timeout not currently used.
        def target():
            P = subprocess.PIPE
            
            arg = ""
            for x in self.args:
                arg += x + " "
            start = time.time()
            last_output = time.time()
            last_input = time.time()

            p = subprocess.Popen(arg, shell=True, stdout=P, stderr=P, stdin=P)
            fd = p.stdout.fileno()
            fl = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
            last_output = time.time()
            last_input = time.time()
            while p.poll() is None:
                (rlist, wlist, xlist) = select.select([p.stdout], [p.stdin], [p.stderr])
                
                # Read the output of the program
                if len(rlist) > 0:
                    s = p.stdout.read()
                    if len(s) > 0:
                        self.out += s
                        last_output = time.time()
                # If we can write, it is more than .5s, and output has occured recently
                if len(wlist) > 0 and time.time() - last_output > 0.5 and time.time()-last_input > 0.5:
                    # Write out the next line of input
                    if len(self.input) > 0:
                        p.stdin.write(self.input[0])
                        del self.input[0]
                        last_input = time.time()
            self.err += p.stderr.read()
        target()
        return self.out, self.err

# Used to create and html file showing the difference between two strings
class Difference(object):
    def __init__(self, solution, student):
        self.solution = solution
        self.student = student
    def target(self, self2, queue):
        solutions = self.solution.splitlines(True)
        students = self.student.splitlines(True)
        for i in range(len(solutions)):
            solutions[i] = solutions[i].rstrip() + "\n"
        for i in range(len(students)):
            students[i] = students[i].rstrip() + "\n"
        htmlDiff = difflib.HtmlDiff()

        queue.put(htmlDiff.make_file(
                                solutions,
                                students,
                                fromdesc='solution',
                                todesc='student'))
        queue.close()

    def run(self, timeout):
        queue = multiprocessing.Queue(1) # Maximum size is 1
        proc = multiprocessing.Process(target=self.target, args=(self, queue))
        proc.start()
        # Wait for TIMEOUT seconds
        try:
            result = queue.get(True, timeout)
        except Queue.Empty:
            # Deal with lack of data somehow
            result = "Wrong\n"
            for line in self.student.splitlines(True):
                result+= line
        finally:
            proc.terminate()
        return result


class rubricLine(object):
    def __init__(self, fullC, graderProp, studentProp) :
        if fullC > 0 :
          self.fc = fullC
          self.dc = fullC     # scores can be deducted
        else :
          self.fc = 0
          self.dc = -fullC
        self.sc = self.fc     # default student score
        self.gp = graderProp
        self.sp = studentProp

    def getStudentScore(self) :
        maxP = self.dc
        if self.fc != 0 :
          self.sc = get_Int(self.gp + '\t' + str(maxP) + ':\t', 0, maxP, maxP)
        else :
          self.sc = get_Int(self.gp + '\t' + str(-maxP) + ':\t', -maxP, 0, 0)

    def isFullCredit(self) :
        return self.sc == self.fc

    def printFeedback(self) :
        return '(-' + str(self.fc - self.sc) + ')  ' +  self.sp 

class rubrics(object):
    def __init__(self):
        self.dicts = defaultdict(list)
        self.kws = []

    def addRubric(self, rl, keyWord) :
        if keyWord not in self.kws :
            self.dicts[keyWord] = []
            self.kws.append(keyWord)
        self.dicts[keyWord].append(rl)

    # get subtotal for a key word, True for student, False for full credit
    def subTotal(self, keyWord, student) :
        assert keyWord in self.dicts
        total = 0
        for rl in self.dicts[keyWord] :
            total += rl.sc if student else rl.fc
        return total

    # get total score, True for student, False for full credit
    def getTotal(self, student) :
        total = 0
        for kw in self.dicts :
            total += self.subTotal(kw, student)
        return max(total, 0)

    def printTotal(self) :
        return "%d/%d" % (self.getTotal(True), self.getTotal(False))

    def printKWScore(self, keyWord) :
        return "%d/%d" % (self.subTotal(keyWord, True), self.subTotal(keyWord, False))

    def getKWdetail(self, keyWord) :
        detail = []
        for rl in self.dicts[keyWord] :
            if not rl.isFullCredit() :
                detail.append(rl.printFeedback())
        return detail

    def getAllKw(self) :
        return self.kws;

    def isFullCredit(self) :
        return self.getTotal(True) == self.getTotal(False)

class format(object) :
    def __init__(self):
        self.out = ""

    def addLine(self, str) :
        self.out += " * %s \n" % str

    def addHeader(self) :
        self.out += "\n/**\n"

    def addFooter(self) :
        self.out += ' */'

    def printScreen(self) :
        print self.out

    def printFile(self, filename) :
        with open(filename, "w") as myfile:
            myfile.write(self.out) 



def move_required(dirname, folder):
    for f in os.listdir(folder):
        copy(dirname, os.path.join(folder, f))

def getInput(source):
    input = ""
    with open(source) as src:
        for line in src:
            input += line
    return input

def move(dirname, source, dest):
    target = os.path.join(dirname, os.path.basename(dest))
    with open(target, 'w') as sink:
        with open(source) as src:
            for line in src:
                sink.write(line)
                
def copy(dirname, source):
    move(dirname, source, source)
    
def getOut(dirname, source):
    ret = ""
    target = os.path.join(dirname, source)
    with open(source) as src:
        for line in src:
            ret += line
    return ret
    
# Compiles a java file at 'source'
def compile(source):
    if not os.path.exists(source):
        raise IOError('File does not exist: %s' % source) 
    logging.debug('%s: compiling', source)
    args = ['javac', '-nowarn', source]
    command = Command(args, '')
    out, err = command.run(timeout=5)
    if out or err:
        raise CompileError(out, err, source)      

# classname - Name of class file to execute
# inputName - Optional file name that contains input for the program
# outputName - Optional file name that contains expected output for the program
def run(classname, inputName, outputName):
    if inputName is not None:
        input = getInput(inputName)
    else:
        input = ''
    print 'Running %s test case' % inputName
    args = ['java', classname]
    command = Command(args, input)
    out, err = command.run(timeout=20)
    # Not currently implemented
    if err == "TIME OUT":
        print "Timed out..."
        return ["TIME OUT", None]
    if err:
        return [out +'\n\n' + err, None]
    if outputName:
        return [out, getOut('.', outputName)]
    else:        
        return [out, None]

def diff(solution, student):
    '''Diff the contents of instructor and student output.'''
    command = Difference(solution, student)
    return command.run(timeout=15)

def runStudent(args, startDir, match_obj, solutions) : 
    filename = match_obj.group(0)
    lastName = match_obj.group(1)
    firstName = match_obj.group(2)
    cid = match_obj.group(3)
    fid = match_obj.group(4)
    htmlName = id2Str(int(fid))
    os.chdir(startDir)
    sourceFolder = os.path.join(startDir, 'work', cid)
    diffFolder = os.path.join(startDir, 'diff', htmlName)
    if not os.path.exists(sourceFolder):
        os.makedirs(sourceFolder)
    if not os.path.exists(diffFolder):
        os.makedirs(diffFolder)

    source = os.path.join(sourceFolder, args.solution)
    origin = os.path.join(startDir, args.turnin, filename)
    move(sourceFolder, origin, source)
    fname = args.solution
    classname = os.path.basename(fname).replace('.java', '')
    print (" %s, %s, (%s): starting tests" % (lastName, firstName, cid))
    print ("running files inside of %s" %(sourceFolder))
    if args.folder:
        move_required(sourceFolder, args.folder)
    os.chdir(sourceFolder)
    try:
        compile(fname)
        io = map(None, args.input, args.output)
        pos = 0
        directory = os.listdir(os.getcwd())
        for cur in io:
            try:
                studPrint, studOut = run(classname, cur[0], cur[1])
                difference = diff(solutions[pos][0], studPrint)
                dest = cid + "_" + cur[0] + '_diff' + '.html'
                diffOut = open(dest, 'w')
                for line in difference:
                    diffOut.write(line)
                diffOut.close()
                if studOut:
                    difference = diff(solutions[pos][1], studOut)
                    dest = eid+"_"+cur[1]+'_diff'+'.html'
                    diffOut = open(dest, 'w')
                    for line in difference:
                        diffOut.write(line)
                    diffOut.close()
            except TimeOutError:
                    # Not implemented
                logging.error("Time Out")
                dest = cid + '_timeout.txt'
                diffOut = open(dest, 'w')
                diffOut.write("Time Out Error")
                diffOut.close()
            except IOError as err:
                error = 'eid ' +str(eid)+': IO error\n'+str(err)
                logging.error(error)
            pos += 1
            copy(diffFolder, dest)
            if args.webbrowser :
                webbrowser.open_new_tab("file://" + os.path.join(diffFolder, dest))
            '''
            newDir = os.listdir(os.getcwd())
            outDir = 'test %s' % pos
            for x in newDir:
                if x not in directory and not os.path.isdir(x):
                    if not os.path.exists(outDir):
                        os.makedirs(outDir)
                    outX = os.path.join(outDir, x)
                    if os.path.exists(os.path.join(outDir, x)):
                        os.remove(os.path.join(outDir, x))
                    os.rename(x, outX)
            '''
    except (CompileError, IOError) as err:
        error = 'cid ' +str(cid)+': compilation failed\n'+str(err)
        logging.error(error)
        dest = os.path.join("compile.txt")
        out = open(dest, 'w')
        out.write(error)
        out.close() 
        return False
    print ("cid %s: finished tests" % (cid))
    return True


# Compile solution and generate golden
def genGolden(args) :
    logging.info('running instructor solution for %d test case(s).', len(args.input))
    dirname = "solution_" + str(args.assignment)
    if not os.path.exists(dirname):
        os.makedirs(dirname)
    if args.folder:
        move_required(dirname, args.folder)
    copy(dirname, args.solution)
    os.chdir(dirname)
    compile(args.solution)
    classname = os.path.basename(args.solution).replace('.java', '')
    solutions = []
    io = map(None, args.input, args.output)
    if len(io) == 0 :
        solutions.append(run(classname, None, None))
    else :
        for cur in io:
            solutions.append(run(classname, cur[0], cur[1]))
    logging.info('Finished instructor solutions')
    return solutions


# Build a dictionary of ID -> Name
def genInfos(args): 
    infos = {}
     # Hard coded values for location of information in canvas csv
    NAME = 0
    ID = 1
    UTEID = 2
    UNIQUE = 4
    SCORE = 8
    pattern = r'([\w\s]*)\(([\d]*)\)'
    
    f = open(args.info)
    try: 
        reader = csv.reader(f)
        reader.next()
        reader.next() ## skip the first two lines
        for line in reader:
            infos[line[ID]] = {}
            infos[line[ID]]['name'] = line[NAME]
            infos[line[ID]]['uteid'] = line[UTEID]
            mo = re.match(pattern, line[UNIQUE])
            if mo is not None: 
                infos[line[ID]]['unique'] = mo.group(2)
            else :
                infos[line[ID]]['unique'] = "Unknown" 
    finally: 
        f.close()
    return infos


# read in rubrics lines 
def getRubrics(args) :
    rpattern = r'([-\d\s]*)\|([\w\s-]*)\|([\w\s-]*)'
    keyWord = ""
    rb = rubrics()
    for line in open(args.rubric):
        match_obj = re.match(rpattern, line)
        if match_obj is None :
            if (isKeyWord(line)) :
                keyWord = line.rstrip().lower()
                '''
                if keyWord == 'style' :
                    os.system('%s %s' % ('more ', origin))
                print "\n" * 3
                print keyWord.upper(), ":"  
                '''
            else : 
                print "Invaild syntax in rubric: ", line
        else :
            fullCredit = int(match_obj.group(1).rstrip())
            graderProp = match_obj.group(2)
            studentProp = match_obj.group(3).rstrip()
            rl = rubricLine(fullCredit, graderProp, studentProp)
            # rl.getStudentScore()
            rb.addRubric(rl, keyWord)
    return rb


# get student feedback from command line
def fillRubrics(rb, file) :
    kws = rb.getAllKw()
    for kw in kws :
        if kw == 'style' :
            os.system('%s %s' % ('more ', file))
        print "\n" * 3
        line = raw_input("'n' to skip  \t %s?" % kw.upper())
        if len(line) > 0 and (line[0] == 'n' or line[0] == 'N') :
            continue
        else :  
            for rl in rb.dicts[kw] :
                rl.getStudentScore()


def getComment(root, mat_obj, scores, slips, infos, args):
    filename = mat_obj.group(0)
    lastName = mat_obj.group(1)
    firstName = mat_obj.group(2)
    cid = mat_obj.group(3)
    fid = mat_obj.group(4)
    htmlName = id2Str(int(fid))
    origin = os.path.join(root, filename)
    print "Grading: " + infos[cid]['name']

    # skip slip day, update slip day using canvas
    ''' 
    os.system('%s %s' % ('head -15', origin))
    slip = get_Int("Slip days used: ", 0, 2, 0)
    slips[cid] = slip
    '''

    rb = getRubrics(args)
    while True : 
        fillRubrics(rb, origin) 
        regrade = raw_input('\'m\' for manual, \'a\' for auto, enter to continue \t Regrade?')
        if len(regrade) == 0 :
            break
        elif regrade[0].lower() == 'm' :
            print "Manual Regrade. Saved to \'regrade\' folder."
            return False 
        elif regrade[0].lower() == 'a' :
            continue
        else :
            break

    pr = format()
    pr.addHeader()
    pr.addLine("Hi %s%s," % (firstName[0].upper(), firstName[1:].lower()))
    pr.addLine("")
    pr.addLine("Here is the feedback for Assignment %d. Let me know if you have any question. " % int(args.assignment))
    pr.addLine("")
    pr.addLine("")
    pr.addLine("Submitted File: %s" % args.solution)
    pr.addLine("Name: %s %s" % (firstName.upper(), lastName.upper()))
    pr.addLine("UT EID: %s" % infos[cid]['uteid'])
    pr.addLine("Section 5 digit ID: %s" % infos[cid]['unique'] )
    pr.addLine("Grader Name: %s" % args.grader)
    pr.addLine("")
    # pr.addLine("Slipday for this assignment: %d" % slip)
    pr.addLine("Total point: %s" % rb.printTotal())
    pr.addLine("")
    
    scores[cid] = rb.getTotal(True)   # get total score for student

    if (rb.isFullCredit()) :
        pr.addLine("Well done!")
        pr.addLine("")
    else :
        kws = rb.getAllKw()
        for kw in kws :
            pr.addLine("%s: %s " %(kw.upper(), rb.printKWScore(kw)))
            details = rb.getKWdetail(kw)
            if len(details) == 0 :
                pr.addLine("Well done!")
            for line in details :
                pr.addLine(str(line))
            pr.addLine("")

    otherComment = raw_input('Other comments to student:')
    if len(otherComment) > 0 :
        pr.addLine("")
        pr.addLine(otherComment)
        pr.addLine("")

    pr.addLine("")
    pr.addLine("Check your diff result at: http://www.cs.utexas.edu/~%s/cs312/a%d/%s" % (args.cslogin, args.assignment, htmlName))
    pr.addLine("")
    pr.addLine("Best, ")
    pr.addLine("%s -- %s@cs.utexas.edu" % (args.grader, args.cslogin) )
    pr.addFooter()

    location = os.path.join(root, filename)
    pr.printFile(location)

    print "=" * 80
    pr.printScreen()
    print "=" * 80
    print "\n" * 3
    return True
    

def isKeyWord(line):
    keyWord = ['correctness', 'style', 'other']
    word = line.rstrip().lower()
    if word in keyWord :
        return True
    return False

# Output the new grades into 'updated_grades.csv'
def update_grades(info, scores, slips, assignment):    
    csid = 0  
    scoreIndex = 0
    slipIndex = 0
    
    f = open('.' + info)   # base file for the format
    reader = csv.reader(f)
    studentData = reader.next()
    outFile = open(info, 'wb')
    writer = csv.writer(outFile, delimiter = ',', quotechar = '"', quoting = csv.QUOTE_MINIMAL)
    writer.writerow(studentData)

    for i in xrange(0, len(studentData)):
        if "Assignment "+ str(assignment) + " " in studentData[i]:
            scoreIndex = i  
        elif "Slip Days (" in studentData[i]:
            slipIndex = i 
        elif "ID" == studentData[i] : 
            csid = i
    
    studentData = reader.next()     #skip second line
    writer.writerow(studentData)
    studentData = reader.next()     #skip third line
    writer.writerow(studentData)

    for studentData in reader:
        id = studentData[csid]
        if id in scores:
            studentData[scoreIndex] = str(scores[id])
        if id in slips:
            slipInfo = studentData[slipIndex]
            if len(slipInfo) > 0 and slipInfo[0].isdigit():
                current = int(slipInfo)
            else:
                current = 0
            total = slips[id] + current
            studentData[slipIndex] = str(total)
            if total > 6:
                print "MAX slip day reached, current: " + str(total)   
            #if current != 0:
                #print studentData[slipIndex]  
        writer.writerow(studentData)

    f.close()
    outFile.close()


def id2Str(num) :
    rst = ''
    while num > 0 :
        rst += getAn(num % 62)
        num /= 62
    return rst

def getAn(num) :
    assert num < 62 and num >= 0
    if num < 10 :
        return str(num)
    elif num < 36 :
        return chr(ord('a') + num - 10)
    else :
        return chr(ord('A') + num - 36)

def get_Int(prop, minV, maxV, deV):
    while True:
        inStr = raw_input(prop)
        if len(inStr) == 0:
            return deV
        else :
            try:
                 intTarget = int(inStr)
            except ValueError:
                 print 'Integer expected'
                 continue
            else:
                if intTarget < minV or intTarget > maxV:
                    print 'range %d - %d' % (minV, maxV)
                    continue
                else:
                    return (intTarget)

def makeFolder(root, name) :
    folder = os.path.join(root, name)
    if not os.path.exists(folder):
        os.makedirs(folder)  
    return folder


def finish(args) :
    print "Finishing grading ..."
    print r"Graded file moved to 'graded'"
    print "Grade have been updated in \'%s\'" % args.info
    print "Todo: "
    print r"1. check 'compilerr' for files with compile error"
    print r"2. check 'wrongName' for files with incorrect name"
    print r"3. check 'regrade' for files to manual regrade"
    print "done"


def main(args):
    assert os.path.isdir(args.turnin)
    startDir = os.getcwd()

    if len(args.input) > 0 and len(args.output) > 0:
        assert len(args.input) == len(args.output)
    solutions = genGolden(args)

    feedbackFolder = makeFolder(startDir, 'feedback')
    compilerrFolder = makeFolder(startDir, 'compilerr')
    wrongNameFolder = makeFolder(startDir, 'wrongName')
    regradeFolder = makeFolder(startDir, 'regrade')
    gradedFolder = makeFolder(startDir, 'graded')

    os.chdir(startDir)
    scores = {}
    slips = {}
    infos = genInfos(args)
    move(startDir, args.info, '.' + args.info)
    
    #             lastN    firstN   cId     fid     fName
    fpattern = r'([\w-]*)--([\w-]*)_([\d]*)_([\d]*)_([\w]*.java)'
    for filename in os.listdir(args.turnin):
        filePath = os.path.join(startDir, args.turnin, filename)
        stop = raw_input("\n\n\nnext student('done' to stop) ?")
        if 'done' in stop :
            break
        match_obj = re.match(fpattern, filename)
        if match_obj is None :
            print "Filename syntex error: ", filename
            continue
        elif match_obj.group(5) != args.solution :
            print "Wrong file name !!! Grade later -> %s\n" % filename
            copy(wrongNameFolder, filePath)
            os.system('%s %s' % ('rm ', filePath))
            continue 
        if not runStudent(args, startDir, match_obj, solutions) :
            print "\nCompile Error !!! Grade later -> %s\n" % filename
            copy(compilerrFolder, filePath)
            os.system('%s %s' % ('rm ', filePath))
            continue

        copy(feedbackFolder, filePath)
        os.chdir(startDir)
        if not getComment(feedbackFolder, match_obj, scores, slips, infos, args):
            copy(regradeFolder, os.path.join(startDir, args.turnin, filename))
            continue
        update_grades(args.info, scores, slips, args.assignment)
        copy(gradedFolder, filePath)
        os.system('%s %s' % ('rm ', filePath))
    finish()
        

if __name__ == '__main__':
    main(FLAGS.parse_args())