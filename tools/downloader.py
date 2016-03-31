#!/usr/bin/env python
import thread
import time
import sys
import argparse
from subprocess import call
import signal
import json
import logging
import fnmatch
import requests
from subprocess import Popen
import cmdparser
import urllib

VIZ_HREF = "http://dlt.incntre.iu.edu:42424"
EXTS     = ["gz", "bz", "zip", "jpg", "png"]
TIMEOUT = 10  # In seconds
parent_attr = 'id'
def signal_handler(signal, frame):
    print('Exiting the program')
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
fs = open("runlors.sh.tmp","w")

def runLors(exlist,viz=False):
    results = []
    for i in exlist:
        href = i['selfRef']
        fname = i['name']
        ext   = fname.split('.')[-1]
        try:
            cmd = 'lors_download -t 10 -b 5m -V 1'
            if viz:
                cmd += ' -X '+viz + ' '
            cmd += ' -f '+ href
            fs.write(cmd + " || : \n")
            # results.append(Popen(cmd.split(" ")))
        except Exception as e:
            logging.info ("ERROR calling lors_download for scene "+ fname + " with error " + str(e))
    for i in results:
        i.wait()

def _download(url,viz=False,ssl=False):
    try:
        logging.info("Url used is " + url)
        if ssl :
            r = requests.get(url,cert=('./dlt-client.pem','./dlt-client.pem'),verify=False)
        else:
            r = requests.get(url)
        js = r.json()
        if not js:
            logging.info("Probably incorrect arguments - or something failed ")
            logging.debug("Url used is " + url + " - Please ensure that unis supports all used features ")
            return
        logging.debug("Response from UNIS " + str(js))
        # print ",".join(map(lambda x : x.get('name'),js))
        runLors(js,viz)
    except ValueError:
        logging.info("Error : Download exnode metadata from Url " + url  + " failed")
        return

def download(host,info,scenes=True,viz=False,reg=False,folder=False,ssl=False,verbose=False):
    url = host + "/exnodes"
    fieldStr = "&fields=selfRef,name&mode=file"
    if reg:
        url += "?metadata.scene=reg=" + urllib.quote(info) + fieldStr
    elif folder:
        url += "?parent=recfind=" + info + fieldStr
    elif scenes:
        """ Process Scene list boolean last since it is always set to true by default """
        url+= "?metadata.scene=" + info + fieldStr
    _download(url,viz)

def get_exnode_json(host,query) :
    query += "&fields=name,mode,id,selfRef,parent";
    url = host + "/exnodes?" + query
    try :
        logging.info("Download exnode metadata from Url " + url)
        js = requests.get(url)
        return js.json()
    except Exception as e :
        print e
        return []

def get_child_json(host,val,qstr='') :
    """ Get the json of all items with this parent recurssively"""
    if not val :
        return []
    js = get_exnode_json(host,"parent="+qstr+val)
    par = []
    ret = []
    for i in js :
        if i.get('mode') == "directory" :
            par.append(i.get(parent_attr))
        elif i.get('mode') == "file":
            ret.append(i)
    ret.extend(get_child_json(host,",".join(par)))
    return ret

def get_from_path(host,path) :
    """ Takes full pathParentattr
    Generate list of queries to actually get a file
    if list of files are
    """
    arr = path.split("/")
    parent = []
    attr = 'name'
    query = "parent=null="
    query += "&"+attr+"="+arr[0]
    parent = get_exnode_json(host,query)
    js = parent
    for i in arr[1:] :
        if parent and i :
            query = "parent=" + ",".join(map(lambda x : x.get(parent_attr),parent))
            query += "&"+attr+"="+i
            js = get_exnode_json(host,query)
            parent = js
    return js

# json = get_from_path("http://dev.crest.iu.edu:8888","Landsat/LC8/008/038/2016")
# json = get_from_path("http://dev.crest.iu.edu:8888","Landsat/LC8/008/")
def runlors_dir(host,parent,flter,vizurl):
    """ recurrsively runlors on file list and use filter """
    """ FIXME This can blow the stack , need to make it non-recurssive"""
    js = get_exnode_json(host,"parent="+parent)
    lorsarr = []
    for i in js :
        if i.get('mode') == "file" and fnmatch.fnmatch(i.get('name'),flter) :
            lorsarr.append(i)
        elif i.get('mode') == "directory" :
            runlors_dir(host,i.get('id'),flter,vizurl)
    runLors(lorsarr,vizurl)

def main ():
    global parent_attr
    args = cmdparser.parseArgs()
    if args.selfref :
        parent_attr = 'selfRef'
    info = args.sceneInfo
    host = args.host
    regex = args.regex
    ssl = args.ssl
    scenes = args.scenes
    folder = args.folder
    path = args.path
    vizurl = args.visualize
    typeStr = 'Scene list' if scenes else 'Regex' if regex else 'Folder Id' if folder else  "Unknown"
    logging.info("Downloading Using info: "+  info +  " and tpye :  " + typeStr)
    if path :
        path = info
        flter = args.filter if args.filter else "*"
        """ Download using folder path  """
        json = get_from_path(host,path)
        lorsarr = []
        for i in json :
            if i.get('mode') == "file" and fnmatch.fnmatch(i.get('name'),flter) :
                lorsarr.append(a)
            elif i.get('mode') == "directory" :
                """ Get all immediate children of dir and run _download on them """
                runlors_dir(host,i.get('id'),flter,vizurl)
                # arr = get_child_json(host,i.get(parent_attr))
                # lorsarr = []
                # for a in arr :
                #     if a.get('mode') == "file" and fnmatch.fnmatch(a.get('name'),flter) :
                #         lorsarr.append(a)
            runLors(lorsarr,vizurl)
    else :
        download(host,info,scenes,vizurl,regex,folder,ssl)
    fs.close()
    cmd = "bash runlors.sh.tmp"
    i = Popen(cmd.split(" "))
    i.wait()
    logging.info("You can delete runlors.sh.tmp - Leaving it for debuggin purpose")

if __name__ == "__main__":
    main()
