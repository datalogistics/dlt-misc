#!/usr/bin/env python
import websocket
import time
import sys
import json
import argparse
from subprocess import call
import logging
import signal

VIZ_HREF = ""
TIMEOUT = 10  # In seconds
QUERY   = ""

def signal_handler(signal, frame):
    print('Exiting the program')
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)


class Listener(object):
    def __init__(self, url, viz):
        self._url = url
        self._viz = viz
        
    def on_message(self, ws, message):
        js = json.loads(message)
        try:
            logging.info("    Found maching scene [{scene}]".format(scene = js['metadata']['scene']))
            href  = js['selfRef']
        except Exception as exp:
            logging.warn("----Improperly encoded exnode - {exp}".format(exp = exp))
            logging.debug(message)
            return
        
        try:
            args = ['lors_download', '-t', '10', '-b', '5m', '-f', href]
            if self._viz:
                args.append('-X')
                args.append(self._viz)
            
            results = call(args)
        except Exception as e:
            logging.warn("----Failure during download - {exp}".format(exp = exp))
            
    def on_error(self, ws, error):
        logging.warn("----Websocket error - {exp}".format(exp = error))
    
    def close_handler(self):
        while not self.start():
            time.sleep(10)
            logging.info("    Attempting to reconnect")
        
    def on_close(self, ws):
        logging.warn("--Remote host closed the connection")
        logging.info("    Attempting to reconnect")
        self.close_handler()
    
    def on_open(self, ws):
        logging.info("  Connected to remote host")
        
    def start(self):
        ws = websocket.WebSocketApp(self._url,
                                    self.on_message = on_message,
                                    self.on_error = on_error,
                                    self.on_close = on_close)
        ws.on_open = self.on_open
        ws.run_forever()
        
        
def constructQuery(args):
    result = { "host": args.host, "port": args.port }
    query = {}
    
    if args.scenes:
        query["metadata.scene"] = { "in": args.scenes.split(',') }
        
    if args.productcode:
        query["metadata.productCode"] = { "in": args.productcode.split(',') }
    
    result["query"] = json.dumps(query)
    return result

def main ():
    form = '[%(asctime)s] %(level)s:%(msg)s'
    logging.basicConfig(format = form, level = logging.INFO)
    parser = argparse.ArgumentParser(
        description="Listen for and then process a particular LANDSAT scene")
    parser.add_argument('-s', '--scenes', type=str, help='Comma-separated list of scenes to look for')
    parser.add_argument('-p', '--productcode', type=str, help='Comma-separated list of products to look for')
    parser.add_argument('-H', '--host', type=str, help='The host name for the exnode UNIS instance',
                        default="dev.crest.iu.edu")
    parser.add_argument('-P', '--port', type=int, help='The port for the exnode UNIS instance',
                        default=8888)
    parser.add_argument('-v', '--verbose', action='store_true', help='Produce verbose output from the script')
    parser.add_argument('-U', '--visualhost', type=str,
                        help='The hostname of the dlt-web client to display visual download information to')
    args = parser.parse_args()
    
    viz = ""
    if args.visualhost:
        viz = args.visualhost
        
    url = "{protocol}://{host}:{port}/subscribe/exnode?query={query}&fields=selfRef,metadata"
    url.format(**constructQuery(args))
    
    logging.info("Listening for scenes....")
    listener = Listener(url, viz)
    listener.start()
    
if __name__ == "__main__":
    main()
