#!/usr/bin/env python3
# coding=UTF-8
#
# bulk_extractor_reader.py:
# A module for working with bulk_extractor

"""
Usage: b=BulkReport(fn)
b.feature_files() = List of feature files
b.carved_files()  = List of carved files
b.histogram_files()    = List of histograms
b.read_histogram() = Returns a dictionary of the histogram
b.open(fname)      = Opens a file in the report directory or zipfile
BulkReport.is_comment_line(line) - returns true if line is a commont line
b.cpu_track() - List of (cpu%, time) tuples
b.rusage() - a dictionary with 'utime', 'stime,' 'maxrss, 'majflt', 'nswap', 'inblocks', 'outblocks', 'clocktime'

Note: files are always opened in binary mode and converted line-by-line
to text mode. The confusion is that ZIP files are always opened as binary
and the "b" cannot be applied, but disk files are default opened in text mode,
so the "b" must be added.

"""


__version__ = "1.5.0"

b'This module needs Python 2.7 or later.'
import zipfile,os,os.path,glob,codecs,re

property_re = re.compile("# ([a-z0-9\-_]+):(.*)",re.I)

MIN_FIELDS_PER_FEATURE_FILE_LINE = 3
MAX_FIELDS_PER_FEATURE_FILE_LINE = 11

import xml.dom.minidom
import xml.parsers.expat
import os.path
import glob
import dfxml
import datetime


def be_version(exe):
    """Returns the version number for a bulk_extractor executable"""
    from subprocess import Popen,PIPE
    return Popen([exe,'-V'],stdout=PIPE).communicate()[0].decode('utf-8').split(' ')[1].strip()

def decode_feature(ffmt):
    """Decodes a feature in a feature file into Unicode"""
    tbin = ffmt.decode('unicode_escape')
    bin = tbin.encode('latin1')
    if b"\000" in bin:
        # If it has a \000 in it, must be UTF-16
        try:
            return bin.decode('utf-16-le')
        except UnicodeDecodeError:
            return tbin
    try:
        return bin.decode('utf-8')
    except UnicodeDecodeError:
        pass
    try:
        return bin.decode('utf-16-le')
    except UnicodeDecodeError:
        pass
    return tbin


def is_comment_line(line):
    if len(line)==0: return False
    if line[:4] == b'\xef\xbb\xbf#': return True
    if line[:1] == '\ufeff':
        line=line[1:]       # ignore unicode BOM
    try:
        if ord(line[0])==65279:
            line=line[1:]       # ignore unicode BOM
    except TypeError:
        pass
    return line[:1] in [b'#', '#']

def is_histogram_line(line):
    return line[:2] == b"n="

def get_property_line(line):
    """If it is a property line return the (property, value)"""
    if line[:1] == '#':
        if m := property_re.search(line):
            return (m.group(1),m.group(2))
    return None

def parse_feature_line(line):
    """Determines if LINE is a line from a feature file. If it is not, return None.
    LINE must be binary.
    If it is, return the fields.
    Previously this assumed that line was in binary; now it assumes that line is in text.
    """
    if len(line)<2: return None
    if line[0]==b'#': return None # can't parse a comment
    if line[-1:]==b'\r': line=line[:-1] # remove \r if it is present (running on Windows?)
    ary = line.split(b"\t")

    # Should have betwen 3 fields (standard feature file)
    # and no more than

    if len(ary)<MIN_FIELDS_PER_FEATURE_FILE_LINE or len(ary)>MAX_FIELDS_PER_FEATURE_FILE_LINE:
        # Don't know
        return None
    if b"\xf4\x80\x80\x9c" in ary[0]: return ary # contains files
    if len(ary[0])<1: return None
    return None if ary[0][0]<ord('0') or ary[0][0]>ord('9') else ary

def is_feature_line(line):
    return bool(parse_feature_line(line))

def is_histogram_filename(fname):
    """Returns true if this is a histogram file"""
    if "_histogram" in fname: return True
    if "url_" in fname: return True # I know this is a histogram file
    return False if fname=="ccn_track2.txt" else None

def is_feature_filename(fname):
    """Returns true if this is a feature file"""
    if not fname.endswith(".txt"): return False
    if "/" in fname: return False # must be in root directory
    if "_histogram" in fname: return False
    if "_stopped" in fname: return False
    if "_tags" in fname: return False
    return False if "wordlist" in fname else None


class BulkReport:
    """Creates an object from a bulk_extractor report. The report can be a directory or a ZIP of a directory.
    Methods that you may find useful:
    f = b.open(fname,mode)     - opens the file f and returns a file handle. mode defaults to 'r'
    b.is_histogram_file(fname) - returns if fname is a histogram file or not
    b.image_filename() - Returns the name of the image file
    b.read_histogram(fn) - Reads a histogram and returns the histogram
    b.histogram_files()     - Set of histogram names
    b.feature_files()
    b.files                  - Set of all files
    b.get_features(fname)   - just get the features
"""


    def __init__(self, name, ):
        """Validates the XML and sets the xmldoc
        @param name - a directory name of a directory containing a report.xml file.
                    - a filename of the report.xml
                    - an XML name without the report directory.
        """
        self.name       = name  # as provided
        self.commonprefix=''
        self.dirname = None     # report directory
        self.fname = None       # xml filename
        self.zipfile = None

        if os.path.basename(name) == "report.xml":
            self.fname   = os.path.abspath( name )
            self.dirname = os.path.dirname( name )
        elif name.endswith(".xml"):
            self.fname   = os.path.abspath( name )
            self.dirname = None
        elif name.endswith(".zip"):
            self.zipfile = zipfile.ZipFile( name )
            self.fname   = None
            self.dirname = None
        elif os.path.isdir(name):
            self.dirname = os.path.abspath( name )
            self.fname   = os.path.join(name, "report.xml")
        else:
            raise RuntimeError(f"Cannot decode: {name}")

        if self.dirname:
            self.all_files = {
                os.path.basename(fn)
                for fn in glob.glob(os.path.join(self.dirname, "*"))
            }

            self.files = {
                os.path.basename(fn)
                for fn in glob.glob(os.path.join(self.dirname, "*.txt"))
            }

        elif self.zipfile:
            # If there is a common prefix, we'll ignore it in is_feature_file()
            self.commonprefix = os.path.commonprefix(self.zipfile.namelist())
            while len(self.commonprefix)>0 and self.commonprefix[-1]!='/':
                self.commonprefix = self.commonprefix[:-1]

            if report_name_list := list(
                filter(lambda f: f.endswith("report.xml"), self.zipfile.namelist())
            ):
                report_name_prefix = report_name_list[0].replace("report.xml","")
            else:
                report_name_prefix = None
            # extract the filenames and make a map from short name to long name.
            self.files = set()
            self.map = {}
            for fn in self.zipfile.namelist():
                short_fn = fn
                if report_name_prefix:
                    short_fn = fn.replace(report_name_prefix,"")
                self.files.add(short_fn)
                self.map[short_fn] = fn

        if self.fname:
            self.docfile = open(self.fname)
        elif self.zipfile:
            self.docfile = self.open("report.xml")
        else:
            raise RuntimeError("No report.xml to analyze")

        self.xmldoc = xml.dom.minidom.parse( self.docfile )

    def image_filename(self):
        """Returns the file name of the disk image that was used."""
        return self.xmldoc.getElementsByTagName("image_filename")[0].firstChild.wholeText

    def image_size(self):
        """Returns the image size of the disk."""
        return int(self.xmldoc.getElementsByTagName("image_size")[0].firstChild.wholeText)

    def version(self):
        """Returns the version of bulk_extractor that made the file."""
        return self.xmldoc.getElementsByTagName("version")[0].firstChild.wholeText

    def threads(self):
        """Returns the number of threads used for scanning."""
        return int((self.xmldoc.getElementsByTagName("configuration")[0]
                .getElementsByTagName("threads")[0].firstChild.wholeText))

    def page_size(self):
        """Returns the size of each page processed."""
        return int((self.xmldoc.getElementsByTagName("configuration")[0]
                .getElementsByTagName("pagesize")[0].firstChild.wholeText))

    def margin_size(self):
        """Returns the size of the overlapping margins around each page."""
        return int((self.xmldoc.getElementsByTagName("configuration")[0]
                .getElementsByTagName("marginsize")[0].firstChild.wholeText))

    def clocktime(self):
        """Returns the total real time elapsed for this run.  Values are in seconds."""
        return float((self.xmldoc.getElementsByTagName("rusage")[0]
                .getElementsByTagName("clocktime")[0].firstChild.wholeText))

    def peak_memory(self):
        """Returns the maximum memory allocated for this run in bytes."""
        return 1024 * int((self.xmldoc.getElementsByTagName("rusage")[0]
                .getElementsByTagName("maxrss")[0].firstChild.wholeText))

    def cpu_track(self):
        """Returns a list of (date,cpu) values """
        return sorted([
            ( datetime.datetime.fromtimestamp(int(e.getAttribute('t'))/1000.0),
              float(e.getAttribute('cpu_percent')))
            for e in self.xmldoc.getElementsByTagName("runtime")[0].getElementsByTagName("debug:cpu_benchmark")])

    def open(self,fname,mode='r'):
        """Opens a named file in the bulk report. Default is text mode.
        """
        # zipfile always opens in Binary mode, but generates an error
        # if the 'b' is present, so remove it if present.
        if self.zipfile:
            mode = mode.replace("b","")
            return self.zipfile.open(self.map[fname],mode=mode)
        else:
            mode = mode.replace("b","")+"b"
            fn = os.path.join(self.dirname,fname)
            return open(fn, mode=mode)

    def count_lines(self,fname):
        return sum(not is_comment_line(line) for line in self.open(fname))

    def is_histogram_file(self,fn):
        if is_histogram_filename(fn)==True: return True
        return next(
            (
                is_histogram_line(line)
                for line in self.open(fn, 'r')
                if not is_comment_line(line)
            ),
            False,
        )

    def feature_file_name(self,fn):
        """Returns the name of the feature file name (fn may be the full path)"""
        return fn[len(self.commonprefix):] if fn.startswith(self.commonprefix) else fn

    def is_feature_file(self,fn):
        """Return true if fn is a feature file"""
        if is_feature_filename(self.feature_file_name(fn))==False:
            return False
        return next(
            (
                is_feature_line(line)
                for line in self.open(fn)
                if not is_comment_line(line)
            ),
            False,
        )

    def histogram_files(self):
        """Returns a list of the histograms, by name"""
        return filter(lambda fn:self.is_histogram_file(fn),self.files)

    def feature_files(self):
        """Returns a list of the feature_files, by name"""
        return sorted(filter(lambda fn:self.is_feature_file(fn),self.files))

    def carved_files(self):
        return sorted(filter(lambda fn:"/" in fn,self.files))

    def read_histogram_entries(self,fn):
        """Read a histogram file and return a dictonary of the histogram. Removes \t(utf16=...) """
        import re
        r = re.compile(b"^n=(\d+)\t(.*)$")
        for line in self.open(fn,'r'):
            if m := r.search(line):
                k = m[2]
                p = k.find(b"\t")
                if p>0:
                    k = k[:p]
                yield (k, int(m[1]))

    def read_histogram(self,fn):
        """Read a histogram file and return a dictonary of the histogram. Removes \t(utf16=...) """
        return {k: int(v) for k, v in self.read_histogram_entries(fn)}

    def read_features(self,fname):
        """Just read the features out of a feature file"""
        """Usage: for (pos,feature,context) in br.read_features("fname")"""
        for line in self.open(fname,"rb"):
            if r := parse_feature_line(line):
                yield r
