import abc
from collections import defaultdict
from itertools import cycle

from libdlt.logging import info

DOWNLOAD_RETRY = 3

class AbstractSchedule(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def setSource(self, source):
        """
        Creates the schedule, source must be provided
        as the list of possible schedule slots.
        """
        pass

    @abc.abstractmethod
    def get(self, context):
        """
        get emits the next value at offset.  Offset
        need not be factor in emission order, such
        as in the default upload case, but may be
        used to request a new attempt at a previous
        offset.
        """
        pass
    

class BaseUploadSchedule(AbstractSchedule):
    def setSource(self, source):
        self._depots = source
        self._ls = cycle(source.keys())

    def get(self, context={}):
        for depot in self._ls:
            if self._depots[depot].enabled:
                return depot

class BaseDownloadSchedule(AbstractSchedule):
    @info("BaseDownloadSchedule")
    def setSource(self, source):
        chunks = defaultdict(list)
        for ext in source:
            chunks[ext.offset].append({"retry": 0, "alloc": ext})
        self._ls = chunks
        
    @info("BaseDownloadSchedule")
    def get(self, context={}):
        offset = context["offset"]
        if offset in self._ls and self._ls[offset]:
            chunk = self._ls[offset].pop()
            if chunk['retry'] < DOWNLOAD_RETRY:
                chunk['retry'] += 1
                self._ls[offset].insert(0, chunk)
            return chunk['alloc']
        else:
            chunk = None
            for k, chunk in self._ls.items():
                if k < offset:
                    for i, ext in enumerate(chunk):
                        if ext['alloc'].size + ext['alloc'].offset > offset:
                            chunk = self._ls[k].pop(i)
                            if chunk['retry'] < DOWNLOAD_RETRY:
                                chunk['retry'] += 1
                                self._ls[k].insert(0, chunk)
                            return ext['alloc']
            print ("No more allocations fulfill request: offset ~ {}".format(offset))
            raise IndexError("No more allocations fulfill request: offset ~ {}".format(offset))
