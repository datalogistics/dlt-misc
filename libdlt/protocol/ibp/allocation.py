'''
@Name:   Allocation.py
@Author: Jeremy Musser
@Data:   04/01/2015

------------------------------

Allocation is a formal definition of the
allocation structure.  It contains keys
that can be used to access data on an IBP
depot.
'''

import logging
from datetime import datetime

from unis.models import Lifetime, schemaLoader
from libdlt.depot import Depot

IBP_EXTENT_URI = "http://unis.crest.iu.edu/schema/exnode/ext/1/ibp#"

IBPExtent = schemaLoader.get_class(IBP_EXTENT_URI)

class Allocation(IBPExtent):
    def initialize(self, data={}):
        super(Allocation, self).initialize(data)
        self._log       = logging.getLogger()
        self.timestamp  = 0
        self.depot      = Depot(data["location"]) if "location" in data else None
        self.lifetime   = Lifetime()
        
    def getStartTime(self):
        return datetime.strptime(self.lifetimes.start, "%Y-%m-%d %H:%M:%S")

    def getEndTime(self):
        return datetime.strptime(self.lifetimes.start, "%Y-%m-%d %H:%M:%S")

    def setStartTime(self, dt):
        self.lifetimes.start = dt.strftime("%Y-%m-%d %H:%M:%S")

    def setEndTime(self, dt):
        self.lifetimes.end = dt.strftime("%Y-%m-%d %H:%M:%S")
        
    def GetReadCapability(self):
        return self.mapping.read

    def GetWriteCapability(self):
        return self.mapping.write

    def GetManageCapability(self):
        return self.mapping.manage
        
    def SetReadCapability(self, read):
        try:
            tmpCap = Capability(read)
        except ValueError as exp:
            self._log.warn("{func:>20}| Unable to create capability - {exp}".format(func = "SetReadCapability", exp = exp))
            return False
        self.mapping.read = str(tmpCap)
        
    def SetWriteCapability(self, write):
        try:
            tmpCap = Capability(write)
        except ValueError as exp:
            self._log.warn("{func:>20}| Unable to create capability - {exp}".format(func = "SetWriteCapability", exp = exp))
            return False
        self.mapping.write = str(tmpCap)

    def SetManageCapability(self, manage):
        try:
            tmpCap = Capability(manage)
        except ValueError as exp:
            self._log.warn("{func:>20}| Unable to create capability - {exp}".format(func = "SetManageCapability", exp = exp))
            return False
        self.mapping.manage = str(tmpCap)

class Capability(object):
    def __init__(self, cap_string):
        try:
            self._cap       = cap_string
            tmpSplit        = cap_string.split("/")
            tmpAddress      = tmpSplit[2].split(":")
            self.key        = tmpSplit[3]
            self.wrmKey     = tmpSplit[4]
            self.code       = tmpSplit[5]
        except Exception as exp:
            raise ValueError('Malformed capability string')

    def __str__(self):
        return self._cap

    def __repr__(self):
        return self.__str__()